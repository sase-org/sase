"""CLI entry point for the bead scale benchmark."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from tests.perf._bead_corpus import generate_corpus
from tests.perf._bead_scale_bench import benchmark_store
from tests.perf._bead_scale_gate import evaluate_gate

__all__ = ["REPO_ROOT", "main"]

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _core_revision() -> str:
    try:
        return (
            (REPO_ROOT / "sase-core-revision.txt").read_text(encoding="utf-8").strip()
        )
    except OSError:
        return "unknown"


def _parse_csv(values: list[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        items.extend(part.strip() for part in value.split(",") if part.strip())
    return items


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
