"""Tests for monitor reconciliation artifact queries and scans."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactIndexQueryWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
)
from sase.monitor.store import list_monitors, reconcile_dead_supervisors

from ._fixtures import DEAD_PID, make_starter_agent, record_from_disk


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


def test_reconcile_dead_supervisors_settle_path_index_queries_do_not_scale_with_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Locked settle/re-read must not issue an index query per candidate."""
    import sase.monitor.store as store_module

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    monkeypatch.setattr(
        store_module, "default_agent_artifact_index_path", lambda: index_path
    )
    monkeypatch.setattr(
        store_module,
        "scan_agent_artifacts",
        lambda *_args, **_kwargs: pytest.fail("reconciliation should use the index"),
    )

    def count_queries(candidate_count: int, *, clock_base: int) -> int:
        dirs = [
            make_starter_agent(
                "proj",
                f"20260812{clock_base + index:06d}",
                f"acme--mon{clock_base}{index}",
                agent_family="acme",
                agent_family_role="monitor",
                monitor_id=f"m{clock_base:05d}{index:06d}",
                monitor_state="running",
                monitor_command="sleep 60",
                monitor_stop_status="MONITORED",
                pid=DEAD_PID,
            )
            for index in range(candidate_count)
        ]
        calls: list[object] = []

        def fake_query(
            path: Path,
            projects_root: Path,
            query: AgentArtifactIndexQueryWire,
            options: AgentArtifactScanOptionsWire,
        ) -> AgentArtifactScanWire:
            del path, query
            calls.append(object())
            return _empty_snapshot(
                projects_root,
                options,
                [record_from_disk(artifacts_dir) for artifacts_dir in dirs],
            )

        monkeypatch.setattr(store_module, "query_agent_artifact_index", fake_query)
        reconciled = reconcile_dead_supervisors(project="proj")
        assert [record.monitor_state for record in reconciled] == [
            "failed"
        ] * candidate_count
        for artifacts_dir in dirs:
            assert (Path(artifacts_dir) / "done.json").exists()
        return len(calls)

    small = count_queries(3, clock_base=120000)
    large = count_queries(8, clock_base=130000)
    assert small == large == 1


def test_reconcile_dead_supervisors_locked_reread_observes_disk_not_stale_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent settle must win even when the index still says running."""
    import sase.monitor.store as store_module

    monitor_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="running",
        monitor_command="sleep 60",
        monitor_stop_status="MONITORED",
        pid=DEAD_PID,
    )
    stale_running = record_from_disk(monitor_dir)
    done_path = Path(monitor_dir) / "done.json"
    done_payload = {
        "outcome": "monitored",
        "monitor_state": "failed",
        "error": "already settled by a concurrent pass",
    }
    done_path.write_text(json.dumps(done_payload), encoding="utf-8")
    meta_path = Path(monitor_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["monitor_state"] = "failed"
    meta["monitor_settled"] = True
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    before = done_path.read_text(encoding="utf-8")

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()

    def fake_query(
        path: Path,
        projects_root: Path,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        del path, query
        return _empty_snapshot(projects_root, options, [stale_running])

    monkeypatch.setattr(
        store_module, "default_agent_artifact_index_path", lambda: index_path
    )
    monkeypatch.setattr(store_module, "query_agent_artifact_index", fake_query)
    monkeypatch.setattr(
        store_module,
        "scan_agent_artifacts",
        lambda *_args, **_kwargs: pytest.fail("reconciliation should use the index"),
    )

    reconciled = reconcile_dead_supervisors(project="proj")

    assert [record.monitor_state for record in reconciled] == ["failed"]
    assert json.loads(done_path.read_text(encoding="utf-8")) == done_payload
    assert done_path.read_text(encoding="utf-8") == before


def _empty_snapshot(
    projects_root: Path,
    options: AgentArtifactScanOptionsWire,
    records: list[AgentArtifactRecordWire] | None = None,
) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(projects_root),
        options=options,
        stats=AgentArtifactScanStatsWire(),
        records=list(records or []),
    )
