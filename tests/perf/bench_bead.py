"""Benchmark the current Python-owned ``sase bead`` implementation.

The Phase A bead migration contract uses this as the reproducible baseline
before later phases move storage/query/mutation work into ``sase-core``.

Run directly:

    python tests/perf/bench_bead.py --runs 5 --output /tmp/bead-bench.json

Use ``--sase-bin /path/to/sase`` to measure an installed console script
instead of ``python -m sase.main.entry`` from the current checkout.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest

from sase.bead import db as db_mod
from sase.bead.config import save_config
from sase.bead.model import Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.bead.workspace import MergedBeadView

pytestmark = pytest.mark.slow


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = max(0, min(len(sorted_vals) - 1, int(round(pct * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def _summarize(values: Iterable[float]) -> dict[str, float]:
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
    return env


def _sase_command(sase_bin: str | None) -> list[str]:
    if sase_bin:
        return [sase_bin]
    return [sys.executable, "-m", "sase.main.entry"]


def _write_project(root: Path, *, issue_count: int, dependency_count: int) -> None:
    beads_dir = root / ".sase_beads"
    beads_dir.mkdir(parents=True, exist_ok=True)
    save_config(
        beads_dir,
        {"issue_prefix": "bench", "next_counter": issue_count + 1, "owner": ""},
    )
    conn = db_mod.init_db(beads_dir / "beads.db")
    try:
        plans = max(1, issue_count // 10)
        for idx in range(issue_count):
            if idx < plans:
                issue = Issue(
                    id=f"bench-{idx + 1}",
                    title=f"Plan {idx + 1}",
                    status=Status.OPEN,
                    issue_type=IssueType.PLAN,
                    created_at=f"2026-01-01T00:{idx % 60:02d}:00Z",
                    updated_at=f"2026-01-01T00:{idx % 60:02d}:00Z",
                )
            else:
                parent_id = f"bench-{(idx % plans) + 1}"
                issue = Issue(
                    id=f"{parent_id}.{(idx // plans) + 1}",
                    title=f"Phase {idx + 1}",
                    status=Status.OPEN,
                    issue_type=IssueType.PHASE,
                    parent_id=parent_id,
                    created_at=f"2026-01-01T01:{idx % 60:02d}:00Z",
                    updated_at=f"2026-01-01T01:{idx % 60:02d}:00Z",
                )
            db_mod.create_issue(conn, issue)

        issue_ids = [issue.id for issue in db_mod.list_issues(conn)]
        for idx in range(min(dependency_count, max(0, len(issue_ids) - 1))):
            db_mod.add_dependency(
                conn,
                issue_ids[idx + 1],
                issue_ids[idx],
                f"2026-01-02T00:{idx % 60:02d}:00Z",
            )
        from sase.bead.jsonl import export_to_jsonl

        export_to_jsonl(conn, beads_dir / "issues.jsonl")
    finally:
        conn.close()


def _bench_shell(
    root: Path,
    *,
    runs: int,
    sase_bin: str | None,
) -> dict[str, dict[str, float]]:
    base = _sase_command(sase_bin)
    scenarios = {
        "list": [*base, "bead", "list"],
        "ready": [*base, "bead", "ready"],
        "show": [*base, "bead", "show", "bench-1"],
    }
    results: dict[str, dict[str, float]] = {}
    for name, command in scenarios.items():
        timings: list[float] = []
        for _ in range(runs):

            def _run(command: list[str] = command) -> None:
                subprocess.run(
                    command,
                    cwd=root,
                    env=_fixed_env(),
                    text=True,
                    capture_output=True,
                    check=True,
                )

            timings.append(_time_call(_run))
        results[name] = _summarize(timings)
    return results


def _bench_project(root: Path, *, runs: int) -> dict[str, dict[str, float]]:
    scenarios: dict[str, Callable[[BeadProject], object]] = {
        "list_issues": lambda project: project.list_issues(),
        "ready": lambda project: project.ready(),
        "show": lambda project: project.show("bench-1"),
    }
    results: dict[str, dict[str, float]] = {}
    for name, fn in scenarios.items():
        timings = [
            _time_call(lambda fn=fn: _with_project(root, fn)) for _ in range(runs)
        ]
        results[name] = _summarize(timings)
    return results


def _with_project(root: Path, fn: Callable[[BeadProject], object]) -> object:
    with BeadProject(root) as project:
        return fn(project)


def _bench_merged(primary: Path, *, runs: int) -> dict[str, dict[str, float]]:
    beads_dirs = sorted(primary.parent.glob("workspace*/.sase_beads"))
    scenarios: dict[str, Callable[[MergedBeadView], object]] = {
        "list_issues": lambda view: view.list_issues(),
        "ready": lambda view: view.ready(),
        "show": lambda view: view.show("bench-1"),
    }
    results: dict[str, dict[str, float]] = {}
    for name, fn in scenarios.items():
        timings = [
            _time_call(lambda fn=fn: _with_merged_view(beads_dirs, fn))
            for _ in range(runs)
        ]
        results[name] = _summarize(timings)
    return results


def _with_merged_view(
    beads_dirs: list[Path],
    fn: Callable[[MergedBeadView], object],
) -> object:
    with MergedBeadView(beads_dirs) as view:
        return fn(view)


def run_benchmark(
    *,
    runs: int,
    issue_count: int,
    dependency_count: int,
    sase_bin: str | None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="sase_bead_bench_") as td:
        root = Path(td) / "workspace"
        root.mkdir()
        _write_project(root, issue_count=issue_count, dependency_count=dependency_count)

        merged_root = Path(td) / "merged"
        merged_root.mkdir()
        for idx in range(3):
            workspace = merged_root / f"workspace{idx + 1}"
            shutil.copytree(root, workspace)

        return {
            "runs": runs,
            "issue_count": issue_count,
            "dependency_count": dependency_count,
            "shell": _bench_shell(root, runs=runs, sase_bin=sase_bin),
            "project": _bench_project(root, runs=runs),
            "merged_workspace": _bench_merged(merged_root / "workspace1", runs=runs),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--issues", type=int, default=399)
    parser.add_argument("--dependencies", type=int, default=200)
    parser.add_argument("--sase-bin")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    results = run_benchmark(
        runs=args.runs,
        issue_count=args.issues,
        dependency_count=args.dependencies,
        sase_bin=args.sase_bin,
    )
    payload = json.dumps(results, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
