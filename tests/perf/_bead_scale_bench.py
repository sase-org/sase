"""Binding, CLI, and TUI bench runners for the bead scale benchmark."""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

__all__ = ["benchmark_store"]


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
