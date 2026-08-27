"""Operation-count benchmark for the Agents-tab disk load path.

This harness is intentionally count-based rather than time-based. It guards
against monitor reconciliation returning to the synchronous ``sase ace`` disk
load by counting proc-store reads, artifact-index queries, and synchronous
reconcile calls while loading synthetic monitor rows.

Run directly with::

    python tests/perf/bench_agent_disk_load_ops.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sase.ace.tui.actions.agents._loading_helpers import (  # noqa: E402
    load_agents_from_disk_with_state,
)
from sase.core.agent_scan_wire import (  # noqa: E402
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactIndexQueryWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
    FamilyShellMonitorWire,
    FamilyShellWire,
)


@dataclass
class _Counters:
    proc_store_reads: int = 0
    artifact_index_queries: int = 0
    loader_index_queries: int = 0
    monitor_reconcile_index_queries: int = 0
    sync_reconcile_calls: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "proc_store_reads": self.proc_store_reads,
            "artifact_index_queries": self.artifact_index_queries,
            "loader_index_queries": self.loader_index_queries,
            "monitor_reconcile_index_queries": self.monitor_reconcile_index_queries,
            "sync_reconcile_calls": self.sync_reconcile_calls,
        }


def run_benchmark(
    *,
    monitor_counts: Iterable[int] = (0, 250),
) -> dict[str, Any]:
    """Run the disk-load operation-count scenarios."""

    scenarios: dict[str, dict[str, int]] = {}
    for monitor_count in monitor_counts:
        counters = _run_scenario(monitor_count=monitor_count)
        scenarios[f"monitors_{monitor_count}"] = counters.as_dict()
    return {
        "schema_version": 1,
        "benchmark": "agent_disk_load_ops",
        "scenarios": scenarios,
    }


def _run_scenario(*, monitor_count: int) -> _Counters:
    counters = _Counters()
    with tempfile.TemporaryDirectory(prefix="sase-agent-disk-load-ops-") as tmp:
        root = Path(tmp)
        sase_home = root / ".sase"
        projects_root = sase_home / "projects"
        projects_root.mkdir(parents=True)
        index_path = sase_home / "agent_artifact_index.sqlite"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.touch()

        previous_sase_home = os.environ.get("SASE_HOME")
        os.environ["SASE_HOME"] = str(sase_home)
        try:
            with ExitStack() as stack:
                _patch_disk_load_dependencies(
                    stack,
                    counters=counters,
                    index_path=index_path,
                    projects_root=projects_root,
                    monitor_count=monitor_count,
                )
                load_agents_from_disk_with_state(
                    set(),
                    patch_snapshot=[],
                    source=f"bench_agent_disk_load_ops_{monitor_count}",
                )
        finally:
            if previous_sase_home is None:
                os.environ.pop("SASE_HOME", None)
            else:
                os.environ["SASE_HOME"] = previous_sase_home
    return counters


def _patch_disk_load_dependencies(
    stack: ExitStack,
    *,
    counters: _Counters,
    index_path: Path,
    projects_root: Path,
    monitor_count: int,
) -> None:
    import sase.monitor as monitor_package
    import sase.procs.store as proc_store

    original_binding = proc_store._call_binding
    original_reconcile = monitor_package.reconcile_dead_supervisors

    def count_binding(name: str, *args: object) -> object:
        if name == "read_procs_snapshot":
            counters.proc_store_reads += 1
            return {"schema_version": 3, "procs": [], "stats": {}}
        return original_binding(name, *args)

    def count_reconcile(*args: object, **kwargs: object) -> object:
        counters.sync_reconcile_calls += 1
        return original_reconcile(*args, **kwargs)

    def loader_query(
        _index_path: Path,
        _projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        del query
        counters.artifact_index_queries += 1
        counters.loader_index_queries += 1
        return _scan(projects_root, options, monitor_count=monitor_count)

    def monitor_reconcile_query(
        _index_path: Path,
        _projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        del query
        counters.artifact_index_queries += 1
        counters.monitor_reconcile_index_queries += 1
        return _scan(projects_root, options, monitor_count=monitor_count)

    stack.enter_context(patch.object(proc_store, "_call_binding", count_binding))
    stack.enter_context(
        patch.object(monitor_package, "reconcile_dead_supervisors", count_reconcile)
    )
    stack.enter_context(
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        )
    )
    stack.enter_context(
        patch(
            "sase.ace.tui.models.agent_loader._projects_root_for_loader",
            return_value=projects_root,
        )
    )
    stack.enter_context(
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            side_effect=loader_query,
        )
    )
    stack.enter_context(
        patch(
            "sase.monitor.store.default_agent_artifact_index_path",
            return_value=index_path,
        )
    )
    stack.enter_context(
        patch("sase.monitor.store.sase_projects_dir", return_value=projects_root)
    )
    stack.enter_context(
        patch(
            "sase.monitor.store.query_agent_artifact_index",
            side_effect=monitor_reconcile_query,
        )
    )
    stack.enter_context(
        patch(
            "sase.monitor.store.scan_agent_artifacts",
            side_effect=AssertionError(
                "monitor reconciliation should not need a fallback source scan"
            ),
        )
    )


def _scan(
    projects_root: Path,
    options: AgentArtifactScanOptionsWire,
    *,
    monitor_count: int,
) -> AgentArtifactScanWire:
    records = [_monitor_record(projects_root, index) for index in range(monitor_count)]
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(projects_root),
        options=options,
        stats=AgentArtifactScanStatsWire(artifact_dirs_visited=monitor_count),
        records=records,
    )


def _monitor_record(projects_root: Path, index: int) -> AgentArtifactRecordWire:
    project_dir = projects_root / "proj"
    timestamp = f"20260812{index:06d}"
    artifact_dir = project_dir / "artifacts" / "ace-run" / timestamp
    monitor_id = f"mon{index:09d}"
    name = f"lane--mon{index}"
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir=str(project_dir),
        project_file=str(project_dir / "proj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(artifact_dir),
        timestamp=timestamp,
        agent_meta=AgentMetaWire(
            name=name,
            cl_name=f"lane-{index}",
            agent_family=f"lane-{index}",
            agent_family_role="monitor",
            family_shell=FamilyShellWire(
                kind="monitor",
                id=monitor_id,
                start_status="MONITORING",
                stop_status="MONITORED",
                state="completed",
                monitor=FamilyShellMonitorWire(
                    command="sleep 60",
                    cwd=str(project_dir),
                    settled=True,
                ),
            ),
            pid=None,
        ),
        done=DoneMarkerWire(
            outcome="completed",
            cl_name=f"lane-{index}",
            name=name,
            family_shell=FamilyShellWire(kind="monitor", state="completed"),
            status_label="MONITORED",
        ),
        has_done_marker=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--monitor-counts",
        type=int,
        nargs="+",
        default=[0, 250],
        help="Synthetic monitor row counts to run.",
    )
    args = parser.parse_args(argv)
    print(json.dumps(run_benchmark(monitor_counts=args.monitor_counts), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
