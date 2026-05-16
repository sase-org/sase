"""Phase 1 perf fixture for the Agents-tab disk loader (bead ``sase-3r.1``).

The Phase 1 deliverables ask for a small local benchmark covering each of
the three real disk-loader paths so future phases can attribute speedups
(or regressions) to specific tiers:

* ``index_query``: ``_query_artifact_index_for_loader`` against a fresh
  on-disk index built from the synthetic artifact tree.
* ``bounded_source_fallback``: ``_artifact_snapshot_for_tui_load`` with
  no index (Tier 1 source-scan fallback, ``max_records=200``).
* ``full_history_source_scan``: ``_artifact_snapshot_for_tui_load`` with
  ``full_history=True`` (Tier 2 reconcile).

The harness builds its own ephemeral ``projects/`` tree and patches
``Path.home`` so it never touches the developer's real ``~/.sase``.

Marked ``slow`` so ``just test`` does not run it. Invoke directly with::

    pytest -s -m slow tests/perf/bench_agent_loader_tiers.py

Or call :func:`run_bench` from another script for ad-hoc measurements.
"""

from __future__ import annotations

import json
import statistics
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.slow


def _build_synthetic_root(
    root: Path,
    *,
    projects: int,
    per_project: int,
) -> Path:
    """Materialize a hermetic ``~/.sase/projects``-style tree."""

    root.mkdir(parents=True, exist_ok=True)
    base_ts = 20260101000000
    for p in range(projects):
        project_name = "home" if p == 0 else f"proj{p:03d}"
        project_dir = root / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / f"{project_name}.sase").write_text("", encoding="utf-8")

        ace_run_dir = project_dir / "artifacts" / "ace-run"
        ace_run_dir.mkdir(parents=True, exist_ok=True)
        for i in range(per_project):
            ts = str(base_ts + p * per_project + i)
            artifact_dir = ace_run_dir / ts
            artifact_dir.mkdir(parents=True, exist_ok=True)
            agent_name = f"{project_name}_agent_{i:04d}"
            (artifact_dir / "agent_meta.json").write_text(
                json.dumps(
                    {
                        "name": agent_name,
                        "model": "claude-opus-4-7",
                        "pid": 100000 + p * 1000 + i,
                    }
                ),
                encoding="utf-8",
            )
            (artifact_dir / "done.json").write_text(
                json.dumps(
                    {
                        "outcome": "completed",
                        "finished_at": 1000.0 + i,
                        "cl_name": f"cl_{p:03d}_{i:04d}",
                        "name": agent_name,
                        "model": "claude-opus-4-7",
                    }
                ),
                encoding="utf-8",
            )
    return root


def _summarize(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"count": 0.0}
    s = sorted(samples)
    return {
        "count": float(len(s)),
        "min_ms": s[0] * 1000.0,
        "median_ms": statistics.median(s) * 1000.0,
        "max_ms": s[-1] * 1000.0,
    }


def _time(fn: Callable[[], Any], *, runs: int, warmup: int) -> dict[str, float]:
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return _summarize(samples)


def _build_index(projects_root: Path, index_path: Path) -> None:
    """Build the persistent artifact index from a synthetic root."""

    from sase.core.agent_scan_facade import rebuild_agent_artifact_index

    rebuild_agent_artifact_index(index_path, projects_root)


def run_bench(
    *,
    projects: int,
    per_project: int,
    runs: int,
    warmup: int,
) -> dict[str, Any]:
    """Time the three Tier-1/Tier-2 disk-loader paths against a synthetic tree."""

    from sase.ace.tui.models import agent_loader

    with tempfile.TemporaryDirectory() as tmp:
        fake_home = Path(tmp) / "home"
        projects_root = fake_home / ".sase" / "projects"
        _build_synthetic_root(projects_root, projects=projects, per_project=per_project)
        index_path = fake_home / ".sase" / "agent_artifact_index.sqlite"
        _build_index(projects_root, index_path)

        def index_query() -> int:
            with patch("pathlib.Path.home", return_value=fake_home):
                result = agent_loader._query_artifact_index_for_loader(
                    full_history=False,
                    agent_search_active=False,
                )
            assert result is not None
            return len(result[0].records)

        # Pre-create an alternate "home" whose .sase has no index file. The
        # ``projects`` directory is symlinked to the populated synthetic
        # tree so the fallback source scan has real work to do.
        no_index_home = fake_home / "no_index"
        (no_index_home / ".sase").mkdir(parents=True, exist_ok=True)
        (no_index_home / ".sase" / "projects").symlink_to(
            projects_root, target_is_directory=True
        )

        def bounded_source_fallback() -> int:
            with patch("pathlib.Path.home", return_value=no_index_home):
                snapshot, _state = agent_loader._artifact_snapshot_for_tui_load(
                    full_history=False,
                    agent_search_active=False,
                )
            return len(snapshot.records)

        def full_history_source_scan() -> int:
            with patch("pathlib.Path.home", return_value=fake_home):
                snapshot, _state = agent_loader._artifact_snapshot_for_tui_load(
                    full_history=True,
                    agent_search_active=False,
                )
            return len(snapshot.records)

        return {
            "tool": "bench_agent_loader_tiers",
            "phase": "1",
            "projects": projects,
            "per_project": per_project,
            "runs": runs,
            "warmup": warmup,
            "scenarios": {
                "index_query": _time(index_query, runs=runs, warmup=warmup),
                "bounded_source_fallback": _time(
                    bounded_source_fallback, runs=runs, warmup=warmup
                ),
                "full_history_source_scan": _time(
                    full_history_source_scan, runs=runs, warmup=warmup
                ),
            },
        }


def _print_report(report: dict[str, Any]) -> None:
    print()
    print(
        f"# bench_agent_loader_tiers projects={report['projects']} "
        f"per_project={report['per_project']} runs={int(report['runs'])} "
        f"warmup={int(report['warmup'])}"
    )
    header = f"{'scenario':<28} {'min_ms':>10} {'median_ms':>12} {'max_ms':>10}"
    print("  " + header)
    print("  " + "-" * len(header))
    for name, summary in report["scenarios"].items():
        if summary.get("count", 0) == 0:
            continue
        print(
            "  " + f"{name:<28} {summary['min_ms']:>10.3f} "
            f"{summary['median_ms']:>12.3f} {summary['max_ms']:>10.3f}"
        )


def test_bench_agent_loader_tiers_smoke() -> None:
    """Sanity-check the harness so a regression in the fixture is caught early."""

    report = run_bench(projects=2, per_project=4, runs=2, warmup=1)
    scenarios = report["scenarios"]
    for name in ("index_query", "bounded_source_fallback", "full_history_source_scan"):
        assert scenarios[name]["count"] == 2.0, scenarios
        assert scenarios[name]["max_ms"] >= 0.0
    _print_report(report)


if __name__ == "__main__":
    _print_report(run_bench(projects=4, per_project=40, runs=10, warmup=2))
