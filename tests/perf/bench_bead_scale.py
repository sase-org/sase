"""Scale-aware bead benchmark over synthetic or copied corpora.

Measures binding reads, CLI commands, mutations, and the TUI Beads board
loader on history-shaped stores, and emits JSON with per-op stats, the
corpus shape, and the core revision. Pass ``--check-gate`` to enforce the
A1 history-independence criteria (sase-1h8.14 ``perf-gate``) instead of
only recording.

Run directly:

    python tests/perf/bench_bead_scale.py --scale 1 --scale 2 \\
        --output /tmp/bead-scale.json

Use ``--store <dir>`` (repeatable) to measure an existing store, for
example a ``tools/bead_scale_corpus`` copy of the live store, instead of
generating a synthetic corpus.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest


pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.perf._bead_corpus import generate_corpus  # noqa: E402


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = max(0, min(len(sorted_vals) - 1, int(round(pct * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def _summarize(values: list[float]) -> dict[str, float]:
    vals = sorted(values)
    if not vals:
        return {"count": 0.0}
    return {
        "count": float(len(vals)),
        "min_ms": vals[0] * 1000.0,
        "median_ms": statistics.median(vals) * 1000.0,
        "p95_ms": _percentile(vals, 0.95) * 1000.0,
        "max_ms": vals[-1] * 1000.0,
    }


def _time_call(fn: Callable[[], object]) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def _fixed_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("SASE_AGENT_NAME", None)
    env.pop("SASE_AGENT_TIMESTAMP", None)
    env.pop("SASE_ARTIFACTS_DIR", None)
    # Automation inside agents sets this; it keeps `bead show` on the same
    # code path it takes for human use instead of the audited-read refusal.
    env["SASE_BEAD_SKIP_VIEW_LOG"] = "1"
    return env


def _sase_command() -> list[str]:
    return [sys.executable, "-m", "sase.main.entry"]


def _core_revision() -> str:
    try:
        return (
            (REPO_ROOT / "sase-core-revision.txt").read_text(encoding="utf-8").strip()
        )
    except OSError:
        return "unknown"


def _pick_ids(beads_dir: Path) -> tuple[str, str, str]:
    """Return (open_id, closed_id, mutate_id) for a corpus."""
    from sase.core import bead_read_facade

    open_id = closed_id = mutate_id = ""
    for issue in bead_read_facade.list_issues(beads_dir):
        if issue.status.value == "closed" and not closed_id:
            closed_id = issue.id
        if issue.status.value != "closed" and not open_id:
            open_id = issue.id
            mutate_id = issue.id
        if open_id and closed_id:
            break
    if not open_id:
        raise RuntimeError(f"corpus at {beads_dir} has no open bead")
    if not closed_id:
        raise RuntimeError(f"corpus at {beads_dir} has no closed bead")
    return open_id, closed_id, mutate_id


def _bench_bindings(
    beads_dir: Path,
    *,
    runs: int,
    only: set[str] | None,
    open_id: str,
    closed_id: str,
    mutate_id: str,
) -> dict[str, dict[str, float]]:
    from sase.bead.model import Status
    from sase.core import bead_mutation_facade, bead_read_facade

    results: dict[str, dict[str, float]] = {}

    def measure(name: str, fn: Callable[[], object]) -> None:
        if only is not None and name not in only:
            return
        results[name] = _summarize([_time_call(fn) for _ in range(runs)])

    measure(
        "show_detail_open",
        lambda: bead_read_facade.show_issue_detail(beads_dir, open_id),
    )
    measure(
        "show_detail_closed",
        lambda: bead_read_facade.show_issue_detail(beads_dir, closed_id),
    )
    measure("ready", lambda: bead_read_facade.ready(beads_dir))
    measure("blocked", lambda: bead_read_facade.blocked(beads_dir))
    measure("list_default", lambda: bead_read_facade.list_issues(beads_dir))
    measure(
        "list_active_page",
        lambda: bead_read_facade.list_issue_page(
            beads_dir,
            statuses=[
                Status.OPEN,
                Status.CLAIMED,
                Status.READY,
                Status.SNOOZED,
                Status.IN_PROGRESS,
            ],
        ),
    )
    measure(
        "list_closed_20",
        lambda: bead_read_facade.list_issues(beads_dir, statuses=[Status.CLOSED])[:20],
    )
    measure("stats", lambda: bead_read_facade.stats(beads_dir))
    measure("search", lambda: bead_read_facade.search(beads_dir, "synthetic"))

    def _append_note(run: list[int]) -> None:
        run[0] += 1
        bead_mutation_facade.append_note(
            beads_dir, mutate_id, f"Scale benchmark note {run[0]}."
        )

    def _update(run: list[int]) -> None:
        run[0] += 1
        bead_mutation_facade.update(
            beads_dir, mutate_id, description=f"Scale benchmark rev {run[0]}."
        )

    if only is None or "note_append" in only:
        counter = [0]
        results["note_append"] = _summarize(
            [_time_call(lambda: _append_note(counter)) for _ in range(runs)]
        )
    if only is None or "update" in only:
        counter = [0]
        results["update"] = _summarize(
            [_time_call(lambda: _update(counter)) for _ in range(runs)]
        )
    return results


def _bench_cli(
    ws_root: Path,
    *,
    runs: int,
    only: set[str] | None,
    open_id: str,
) -> dict[str, dict[str, float]]:
    base = _sase_command()
    results: dict[str, dict[str, float]] = {}

    def measure(name: str, command: list[str]) -> None:
        if only is not None and name not in only:
            return

        def _run() -> None:
            subprocess.run(
                command,
                cwd=ws_root,
                env=_fixed_env(),
                text=True,
                capture_output=True,
                check=True,
            )

        results[name] = _summarize([_time_call(_run) for _ in range(runs)])

    measure("cli_show", [*base, "bead", "show", open_id])
    measure("cli_ready", [*base, "bead", "ready"])
    return results


def _bench_cli_note(
    ws_root: Path,
    *,
    runs: int,
    only: set[str] | None,
    mutate_id: str,
) -> dict[str, dict[str, float]]:
    if only is not None and "cli_note" not in only:
        return {}
    base = _sase_command()
    counter = [0]
    timings = []
    for _ in range(runs):
        counter[0] += 1
        command = [
            *base,
            "bead",
            "note",
            mutate_id,
            f"Scale benchmark CLI note {counter[0]}.",
        ]

        def _run(command: list[str] = command) -> None:
            subprocess.run(
                command,
                cwd=ws_root,
                env=_fixed_env(),
                text=True,
                capture_output=True,
                check=True,
            )

        timings.append(_time_call(_run))
    return {"cli_note": _summarize(timings)}


def _bench_tui(
    beads_dir: Path,
    ws_root: Path,
    *,
    runs: int,
    only: set[str] | None,
) -> dict[str, dict[str, float]]:
    if only is not None and not ({"tui_board", "tui_snapshot", "tui_cached"} & only):
        return {}
    from sase.ace.tui.widgets.artifacts import beads_data
    from sase.ace.tui.widgets.artifacts.plans_data_models import PlansProject

    item = PlansProject("bench-scale", "bench-scale", str(ws_root))
    saved = (
        beads_data._resolve_projects,
        beads_data._project_beads_dir,
        beads_data._project_document_roots,
    )

    def _patched_resolve_projects(project: object) -> object:
        return (item,)

    def _patched_beads_dir(project: object) -> object:
        return beads_dir

    def _patched_document_roots(probe: object) -> object:
        return {}

    beads_data._resolve_projects = _patched_resolve_projects  # type: ignore[assignment]
    beads_data._project_beads_dir = _patched_beads_dir  # type: ignore[assignment]
    beads_data._project_document_roots = _patched_document_roots  # type: ignore[assignment]
    results: dict[str, dict[str, float]] = {}
    try:
        from sase.ace.tui.widgets.artifacts.beads_data_sources import (
            load_project_beads,
        )

        if only is None or "tui_board" in only:
            results["tui_board"] = _summarize(
                [_time_call(lambda: load_project_beads(beads_dir)) for _ in range(runs)]
            )
        if only is None or "tui_snapshot" in only or "tui_cached" in only:
            snapshot = beads_data.load_beads_snapshot(None, include_external=False)
            if only is None or "tui_snapshot" in only:
                results["tui_snapshot"] = _summarize(
                    [
                        _time_call(
                            lambda: beads_data.load_beads_snapshot(
                                None, include_external=False
                            )
                        )
                        for _ in range(runs)
                    ]
                )
            if only is None or "tui_cached" in only:
                results["tui_cached"] = _summarize(
                    [
                        _time_call(
                            lambda: beads_data.load_beads_snapshot(
                                None, previous=snapshot, include_external=False
                            )
                        )
                        for _ in range(runs)
                    ]
                )
    finally:
        (
            beads_data._resolve_projects,
            beads_data._project_beads_dir,
            beads_data._project_document_roots,
        ) = saved
    return results


def _git_identity(beads_dir: Path) -> None:
    for key, value in (
        ("user.name", "SASE Benchmark"),
        ("user.email", "bench@example.invalid"),
    ):
        existing = subprocess.run(
            ["git", "config", key], cwd=beads_dir, capture_output=True, text=True
        )
        if existing.returncode != 0 or not existing.stdout.strip():
            subprocess.run(
                ["git", "config", key, value],
                cwd=beads_dir,
                check=True,
                capture_output=True,
            )


def _setup_bare_remote(beads_dir: Path, remote_dir: Path) -> None:
    subprocess.run(
        ["git", "init", "--bare", str(remote_dir)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote_dir)],
        cwd=beads_dir,
        check=True,
        capture_output=True,
    )


def benchmark_store(
    beads_dir: Path,
    ws_root: Path,
    *,
    runs: int,
    only: set[str] | None,
    with_remote: bool,
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    """Benchmark one laid-out corpus; return (ops, shape)."""
    from tests.perf._bead_corpus import summarize_corpus

    _git_identity(beads_dir)
    if with_remote:
        _setup_bare_remote(beads_dir, ws_root / "remote.git")
    open_id, closed_id, mutate_id = _pick_ids(beads_dir)
    ops: dict[str, dict[str, float]] = {}
    ops.update(
        _bench_bindings(
            beads_dir,
            runs=runs,
            only=only,
            open_id=open_id,
            closed_id=closed_id,
            mutate_id=mutate_id,
        )
    )
    ops.update(_bench_cli(ws_root, runs=runs, only=only, open_id=open_id))
    ops.update(_bench_cli_note(ws_root, runs=runs, only=only, mutate_id=mutate_id))
    ops.update(_bench_tui(beads_dir, ws_root, runs=runs, only=only))
    return ops, summarize_corpus(beads_dir)


def _parse_csv(values: list[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        items.extend(part.strip() for part in value.split(",") if part.strip())
    return items


# A1 history-independence gate (sase-1h8.14 perf-gate). Ratio criteria
# compare the largest corpus against the smallest one measured in the same
# run, so both sides see the same host load. Absolute criteria use the
# median (the first repetition cold-builds the read model; the median of
# three is a warm read). ``list`` here is the paged active-status query
# that default ``sase bead list`` runs (list_issue_page), not the unbounded
# list_issues dump; the TUI no-change refresh is the cached snapshot path.
GATE_RATIO_OPS = (
    ("ratio:ready", "ready"),
    ("ratio:list", "list_active_page"),
    ("ratio:detail", "show_detail_open"),
    ("ratio:note", "note_append"),
    ("ratio:update", "update"),
)
GATE_ABSOLUTE_OPS = (
    # (criterion id, op, stat, ceiling_ms)
    ("abs:point-read", "show_detail_open", "median_ms", 20.0),
    ("abs:active-list", "list_active_page", "median_ms", 50.0),
    ("abs:tui-nochange", "tui_cached", "median_ms", 100.0),
)


def _stat(
    corpora: list[dict[str, Any]], scale: Any, op: str, field: str
) -> float | None:
    for corpus in corpora:
        if corpus.get("scale") == scale and op in corpus["ops"]:
            return float(corpus["ops"][op].get(field, 0.0))
    return None


def evaluate_gate(
    corpora: list[dict[str, Any]],
    *,
    tolerance: float,
    allowed_misses: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """Check A1 criteria; return (rows, exit_code).

    Every criterion is always evaluated and reported. Criteria named in
    ``allowed_misses`` are recorded as known misses (with their measured
    breakdown) without failing the run; anything else that misses fails.
    Known misses must cite the bead follow-up that owns the fix, so the
    threshold is never loosened silently.
    """
    scales = sorted(
        {c["scale"] for c in corpora if c.get("scale") is not None},
        key=float,
    )
    rows: list[dict[str, Any]] = []
    if len(scales) < 2:
        rows.append(
            {
                "criterion": "gate:needs-two-scales",
                "status": "error",
                "detail": "ratio criteria need at least two --scale corpora",
            }
        )
        return rows, 2
    lo, hi = scales[0], scales[-1]
    for criterion, op in GATE_RATIO_OPS:
        lo_v = _stat(corpora, lo, op, "p95_ms")
        hi_v = _stat(corpora, hi, op, "p95_ms")
        if lo_v is None or hi_v is None:
            rows.append(
                {
                    "criterion": criterion,
                    "status": "error",
                    "detail": f"op {op!r} was not measured at both scales",
                }
            )
            continue
        ratio = (hi_v / lo_v) if lo_v > 0 else float("inf")
        ceiling = 1.0 + tolerance
        ok = ratio <= ceiling
        rows.append(
            {
                "criterion": criterion,
                "status": "pass" if ok else "fail",
                "op": op,
                "lo_scale": lo,
                "hi_scale": hi,
                "lo_p95_ms": round(lo_v, 1),
                "hi_p95_ms": round(hi_v, 1),
                "ratio": round(ratio, 3),
                "ceiling": round(ceiling, 3),
            }
        )
    check_scales = scales
    for criterion, op, field, ceiling_ms in GATE_ABSOLUTE_OPS:
        worst_scale: Any = None
        worst_val = 0.0
        missing = False
        for scale in check_scales:
            val = _stat(corpora, scale, op, field)
            if val is None:
                missing = True
                break
            if val > worst_val:
                worst_val = val
                worst_scale = scale
        if missing:
            rows.append(
                {
                    "criterion": criterion,
                    "status": "error",
                    "detail": f"op {op!r} was not measured at every scale",
                }
            )
            continue
        ok = worst_val <= ceiling_ms
        rows.append(
            {
                "criterion": criterion,
                "status": "pass" if ok else "fail",
                "op": op,
                "worst_scale": worst_scale,
                "worst_median_ms": round(worst_val, 1),
                "ceiling_ms": ceiling_ms,
            }
        )
    exit_code = 0
    for row in rows:
        if row["status"] == "error":
            exit_code = 2
        elif row["status"] == "fail" and row["criterion"] not in allowed_misses:
            exit_code = 1
    for row in rows:
        if row["status"] == "fail" and row["criterion"] in allowed_misses:
            row["status"] = "known-miss"
    return rows, exit_code


def _print_gate(rows: list[dict[str, Any]]) -> None:
    print("---------- A1 history-independence gate ----------")
    for row in rows:
        criterion = row["criterion"]
        status = row["status"].upper()
        if "ratio" in row:
            print(
                f"{criterion:18s} {status:10s} {row['op']}: "
                f"p95 {row['lo_p95_ms']}ms @ {row['lo_scale']}x -> "
                f"{row['hi_p95_ms']}ms @ {row['hi_scale']}x "
                f"(ratio {row['ratio']}, ceiling {row['ceiling']})"
            )
        elif "worst_median_ms" in row:
            print(
                f"{criterion:18s} {status:10s} {row['op']}: "
                f"worst median {row['worst_median_ms']}ms "
                f"@ {row['worst_scale']}x (ceiling {row['ceiling_ms']}ms)"
            )
        else:
            print(f"{criterion:18s} {status:10s} {row.get('detail', '')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark bead reads, mutations, and the TUI board loader on "
            "scaled corpora. One --scale value generates one synthetic "
            "corpus; --store measures an existing store instead. Emits JSON "
            "with per-op p50/p95/max, the corpus shape, and the core "
            "revision. Without --check-gate no thresholds are enforced."
        )
    )
    parser.add_argument(
        "-n",
        "--runs",
        type=int,
        default=3,
        help="Timing repetitions per op (default: 3).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write the JSON report here instead of stdout.",
    )
    parser.add_argument(
        "-s",
        "--scale",
        action="append",
        type=float,
        default=[],
        help="Generate a synthetic corpus at this scale (repeatable).",
    )
    parser.add_argument(
        "-t",
        "--store",
        action="append",
        type=Path,
        default=[],
        help=(
            "Measure an existing beads directory (repeatable). The store "
            "is mutated by the mutation ops, so point it at a scratch copy."
        ),
    )
    parser.add_argument(
        "-e",
        "--seed",
        type=int,
        default=20261006,
        help="Deterministic corpus seed (default: 20261006).",
    )
    parser.add_argument(
        "-y",
        "--only",
        action="append",
        default=[],
        help="Comma-separated op subset to run (repeatable).",
    )
    parser.add_argument(
        "-r",
        "--remote",
        action="store_true",
        help="Point the corpus at a local bare git remote for cli_note.",
    )
    parser.add_argument(
        "-g",
        "--check-gate",
        action="store_true",
        help=(
            "Enforce the A1 history-independence gate on the measured "
            "corpora and exit non-zero on a miss."
        ),
    )
    parser.add_argument(
        "--gate-tolerance",
        type=float,
        default=0.10,
        help=(
            "Allowed fractional p95 move from the smallest to the "
            "largest corpus (default: 0.10, the strict A1 bound; CI "
            "passes a looser runner-noise calibration)."
        ),
    )
    parser.add_argument(
        "--gate-allow",
        action="append",
        default=[],
        help=(
            "Comma-separated criterion ids treated as known misses: "
            "still measured and reported, but not fatal. Each id must "
            "cite the bead follow-up that owns the fix."
        ),
    )
    args = parser.parse_args(argv)

    if not args.scale and not args.store:
        parser.error("pass at least one of --scale or --store")
    only = set(_parse_csv(args.only)) or None
    revision = _core_revision()
    try:
        with open("/proc/loadavg", encoding="utf-8") as fh:
            host_load = fh.read().strip()
    except OSError:
        host_load = "unknown"
    corpora: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="sase_bead_scale_") as td:
        for scale in args.scale:
            ws_root = Path(td) / f"scale_{scale:g}" / "ws"
            beads_dir = ws_root / "sdd" / "beads"
            beads_dir.parent.mkdir(parents=True)
            generate_corpus(beads_dir, scale=scale, seed=args.seed)
            ops, shape = benchmark_store(
                beads_dir, ws_root, runs=args.runs, only=only, with_remote=args.remote
            )
            corpora.append({"scale": scale, "store": None, "shape": shape, "ops": ops})
        for index, store in enumerate(args.store):
            # CLI resolution needs a workspace layout, so measure through a
            # scratch root that links the store in as ./sdd/beads.
            ws_root = Path(td) / f"store_{index}" / "ws"
            (ws_root / "sdd").mkdir(parents=True)
            (ws_root / "sdd" / "beads").symlink_to(Path(store).resolve())
            ops, shape = benchmark_store(
                Path(store),
                ws_root,
                runs=args.runs,
                only=only,
                with_remote=False,
            )
            corpora.append(
                {"scale": None, "store": str(store), "shape": shape, "ops": ops}
            )
    payload: dict[str, Any] = {
        "tool": "bench_bead_scale",
        "core_revision": revision,
        "runs": args.runs,
        "host_loadavg": host_load,
        "corpora": corpora,
    }
    exit_code = 0
    if args.check_gate:
        gate_rows, exit_code = evaluate_gate(
            corpora,
            tolerance=args.gate_tolerance,
            allowed_misses=set(_parse_csv(args.gate_allow)),
        )
        payload["gate"] = {
            "tolerance": args.gate_tolerance,
            "allowed_misses": sorted(set(_parse_csv(args.gate_allow))),
            "rows": gate_rows,
        }
        _print_gate(gate_rows)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
