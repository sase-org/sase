"""Tests for monitor reconciliation artifact queries and scans."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
)
from sase.monitor.store import list_monitors, reconcile_dead_supervisors


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def test_reconcile_dead_supervisors_uses_bounded_active_monitor_index_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.monitor.store as store_module

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    calls: list[
        tuple[
            Path,
            Path,
            AgentArtifactIndexQueryWire,
            AgentArtifactScanOptionsWire,
        ]
    ] = []

    def fake_query(
        path: Path,
        projects_root: Path,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        calls.append((path, projects_root, query, options))
        return _empty_snapshot(projects_root, options)

    monkeypatch.setattr(
        store_module,
        "default_agent_artifact_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(store_module, "query_agent_artifact_index", fake_query)
    monkeypatch.setattr(
        store_module,
        "scan_agent_artifacts",
        lambda *_args, **_kwargs: pytest.fail("reconciliation should use the index"),
    )

    assert reconcile_dead_supervisors(project="proj") == []

    assert len(calls) == 1
    _, _, query, options = calls[0]
    assert query.include_active is True
    assert query.include_recent_completed is False
    assert query.include_full_history is False
    assert query.active_limit == 1000
    assert query.recent_completed_limit == 0
    assert query.include_hidden is True
    assert query.only_monitors is True
    assert options.only_workflow_dirs == ("ace-run",)
    assert options.include_prompt_step_markers is False
    assert options.include_raw_prompt_snippets is False
    assert options.only_projects == ("proj",)
    assert options.max_records == 0
    assert options.newest_first is True


def test_reconcile_dead_supervisors_fallback_scan_stays_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.monitor.store as store_module

    calls: list[tuple[Path, AgentArtifactScanOptionsWire]] = []

    def fake_scan(
        projects_root: Path,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        calls.append((projects_root, options))
        return _empty_snapshot(projects_root, options)

    monkeypatch.setattr(
        store_module,
        "default_agent_artifact_index_path",
        lambda: tmp_path / "missing.sqlite",
    )
    monkeypatch.setattr(store_module, "scan_agent_artifacts", fake_scan)

    assert reconcile_dead_supervisors(project="proj") == []

    assert len(calls) == 1
    _, options = calls[0]
    assert options.only_workflow_dirs == ("ace-run",)
    assert options.include_prompt_step_markers is False
    assert options.include_raw_prompt_snippets is False
    assert options.only_projects == ("proj",)
    assert options.max_records == 0
    assert options.newest_first is True


def test_list_monitors_keeps_full_history_listing_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.monitor.store as store_module
    import sase.procs.service as proc_service

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    calls: list[
        tuple[
            Path,
            Path,
            AgentArtifactIndexQueryWire,
            AgentArtifactScanOptionsWire,
        ]
    ] = []

    def fake_query(
        path: Path,
        projects_root: Path,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        calls.append((path, projects_root, query, options))
        return _empty_snapshot(projects_root, options)

    monkeypatch.setattr(proc_service, "reconcile_proc_shells", lambda: None)
    monkeypatch.setattr(
        store_module,
        "reconcile_dead_supervisors",
        lambda *, project, snapshot=None: [],
    )
    monkeypatch.setattr(
        store_module,
        "default_agent_artifact_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(store_module, "query_agent_artifact_index", fake_query)
    monkeypatch.setattr(
        store_module,
        "scan_agent_artifacts",
        lambda *_args, **_kwargs: pytest.fail("listing should use the index"),
    )

    assert list_monitors(project="proj") == []

    assert len(calls) == 1
    _, _, query, options = calls[0]
    assert query.include_active is True
    assert query.include_recent_completed is True
    assert query.include_full_history is True
    assert query.active_limit is None
    assert query.recent_completed_limit is None
    assert query.include_hidden is True
    assert query.only_monitors is True
    assert options.only_workflow_dirs == ("ace-run",)
    assert options.only_projects == ("proj",)
    assert options.max_records is None
    assert options.newest_first is False


def _empty_snapshot(
    projects_root: Path,
    options: AgentArtifactScanOptionsWire,
) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(projects_root),
        options=options,
        stats=AgentArtifactScanStatsWire(),
        records=[],
    )
