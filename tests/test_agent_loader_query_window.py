from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sase.ace.tui.models._agent_loader_artifacts import (
    artifact_snapshot_for_tui_load,
    query_artifact_index_for_loader,
)
from sase.ace.tui.models.agent_loader import AgentLoadState, load_tiered_agents
from sase.core.agent_scan_facade import (
    query_agent_artifact_index,
    rebuild_agent_artifact_index,
    scan_agent_artifacts,
)
from sase.feature_flags import override_flags
from tests._agent_loader_helpers import _empty_artifact_snapshot
from tests._agents_tab_query_helpers import _make_agent


def test_load_tiered_agents_uses_bounded_safe_query_pushdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sase-zf.2: the legacy pushdown compiler stays exercised with the flag off."""
    target = _make_agent(cl_name="target")
    later_target = _make_agent(cl_name="target-later")
    calls: list[dict[str, object]] = []

    def fake_load_agents_with_state(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            agents=[target, later_target],
            workflow_agent_steps=[],
            state=AgentLoadState(
                tier="tier1",
                complete_history=False,
                artifact_source="artifact_index",
                used_artifact_index=True,
                bounded_prefix=True,
                requested_limit=1,
                returned_count=2,
                has_more=False,
            ),
        )

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._load_agents_with_load_state",
        fake_load_agents_with_state,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._normalize_loaded_agents",
        lambda agents, _steps: list(agents),
    )

    with override_flags(agents_unified_query=False):
        agents, state = load_tiered_agents(search_query="cl:target", requested_limit=1)

    assert agents == [target]
    assert state.returned_count == 1
    assert state.has_more is True
    assert calls == [
        {
            "patch_snapshot": None,
            "full_history": False,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "requested_limit": 1,
            "candidate_filter": {
                "kind": "contains",
                "field": "cl",
                "value": "target",
            },
        }
    ]


def test_load_tiered_agents_unified_query_uses_bounded_pushdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sase-zf.3: with the flag on, safe live-profile queries push down."""
    target = _make_agent(cl_name="target")
    later_target = _make_agent(cl_name="target-later")
    calls: list[dict[str, object]] = []

    def fake_load_agents_with_state(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            agents=[target, later_target],
            workflow_agent_steps=[],
            state=AgentLoadState(
                tier="tier1",
                complete_history=False,
                artifact_source="artifact_index",
                used_artifact_index=True,
                bounded_prefix=True,
                requested_limit=1,
                returned_count=2,
                has_more=False,
            ),
        )

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._load_agents_with_load_state",
        fake_load_agents_with_state,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._normalize_loaded_agents",
        lambda agents, _steps: list(agents),
    )

    with override_flags(agents_unified_query=True):
        agents, state = load_tiered_agents(search_query="cl:target", requested_limit=1)

    assert agents == [target]
    assert state.returned_count == 1
    assert state.has_more is True
    assert calls == [
        {
            "patch_snapshot": None,
            "full_history": False,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "requested_limit": 1,
            "candidate_filter": {
                "kind": "contains",
                "field": "cl",
                "value": "target",
            },
        }
    ]


def test_load_tiered_agents_unsupported_query_uses_full_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_load_agents_with_state(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            agents=[],
            workflow_agent_steps=[],
            state=AgentLoadState(
                tier="tier2",
                complete_history=True,
                artifact_source="source_scan",
                used_artifact_index=False,
            ),
        )

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._load_agents_with_load_state",
        fake_load_agents_with_state,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._normalize_loaded_agents",
        lambda agents, _steps: list(agents),
    )

    with override_flags(agents_deferred_history=False):
        _agents, state = load_tiered_agents(
            search_query="status:failed",
            requested_limit=25,
        )

    assert state.complete_history is True
    assert calls == [
        {
            "patch_snapshot": None,
            "full_history": True,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "requested_limit": None,
            "candidate_filter": None,
        }
    ]


def test_load_tiered_agents_deferred_history_uses_bounded_unified_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = _make_agent(status="FAILED", cl_name="a")
    running = _make_agent(status="RUNNING", cl_name="b")
    calls: list[dict[str, object]] = []

    def fake_load_agents_with_state(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            agents=[failed, running],
            workflow_agent_steps=[],
            state=AgentLoadState(
                tier="tier1",
                complete_history=False,
                artifact_source="artifact_index",
                used_artifact_index=True,
                bounded_prefix=True,
                requested_limit=25,
                returned_count=2,
                has_more=True,
            ),
        )

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._load_agents_with_load_state",
        fake_load_agents_with_state,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._normalize_loaded_agents",
        lambda agents, _steps: list(agents),
    )

    with override_flags(
        agents_deferred_history=True,
        agents_unified_query=True,
    ):
        agents, state = load_tiered_agents(
            search_query="status:FAILED",
            requested_limit=25,
        )

    assert agents == [failed]
    assert state.query_incomplete is True
    assert state.needs_full_history_reconcile is True
    assert state.returned_count == 1
    assert state.has_more is True
    assert calls == [
        {
            "patch_snapshot": None,
            "full_history": False,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "requested_limit": 25,
            "candidate_filter": None,
        }
    ]


def test_load_tiered_agents_deferred_history_uses_bounded_legacy_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = _make_agent(status="FAILED", cl_name="a")
    running = _make_agent(status="RUNNING", cl_name="b")
    calls: list[dict[str, object]] = []

    def fake_load_agents_with_state(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            agents=[failed, running],
            workflow_agent_steps=[],
            state=AgentLoadState(
                tier="tier1",
                complete_history=False,
                artifact_source="artifact_index",
                used_artifact_index=True,
                bounded_prefix=True,
                requested_limit=25,
                returned_count=2,
                has_more=True,
            ),
        )

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._load_agents_with_load_state",
        fake_load_agents_with_state,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._normalize_loaded_agents",
        lambda agents, _steps: list(agents),
    )

    with override_flags(
        agents_deferred_history=True,
        agents_unified_query=False,
    ):
        agents, state = load_tiered_agents(
            search_query="status:failed",
            requested_limit=25,
        )

    assert agents == [failed]
    assert state.query_incomplete is True
    assert state.needs_full_history_reconcile is True
    assert calls == [
        {
            "patch_snapshot": None,
            "full_history": False,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "requested_limit": 25,
            "candidate_filter": None,
        }
    ]


def test_load_tiered_agents_full_history_preserves_safe_candidate_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_load_agents_with_state(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            agents=[],
            workflow_agent_steps=[],
            state=AgentLoadState(
                tier="tier2",
                complete_history=True,
                artifact_source="artifact_index",
                used_artifact_index=True,
            ),
        )

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._load_agents_with_load_state",
        fake_load_agents_with_state,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._normalize_loaded_agents",
        lambda agents, _steps: list(agents),
    )

    with override_flags(agents_unified_query=True):
        _agents, state = load_tiered_agents(
            full_history=True,
            search_query="cl:target",
            requested_limit=25,
        )

    assert state.complete_history is True
    assert calls == [
        {
            "patch_snapshot": None,
            "full_history": True,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "requested_limit": None,
            "candidate_filter": {
                "kind": "contains",
                "field": "cl",
                "value": "target",
            },
        }
    ]


def test_full_history_uses_revalidated_artifact_index_when_flag_enabled() -> None:
    snapshot = _empty_artifact_snapshot()
    mock_scan = Mock()

    def load_index(**kwargs: object) -> tuple[object, AgentLoadState]:
        assert kwargs == {
            "full_history": True,
            "freshness": "cached",
            "requested_limit": None,
            "candidate_filter": {
                "kind": "contains",
                "field": "cl",
                "value": "target",
            },
        }
        return (
            snapshot,
            AgentLoadState(
                tier="tier2",
                complete_history=True,
                artifact_source="artifact_index",
                used_artifact_index=True,
            ),
        )

    with override_flags(agents_index_full_history=True):
        loaded_snapshot, state = artifact_snapshot_for_tui_load(
            full_history=True,
            use_artifact_index=True,
            candidate_filter={
                "kind": "contains",
                "field": "cl",
                "value": "target",
            },
            scan_artifacts=mock_scan,
            load_tier1_index=load_index,
        )

    assert loaded_snapshot is snapshot
    assert state.artifact_source == "artifact_index"
    assert state.used_artifact_index is True
    assert state.complete_history is True
    mock_scan.assert_not_called()


def test_full_history_index_loader_uses_pure_revalidated_history_wire(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = _empty_artifact_snapshot()
    mock_query = Mock(return_value=snapshot)

    loaded_snapshot, state = query_artifact_index_for_loader(
        full_history=True,
        freshness="cached",
        requested_limit=25,
        candidate_filter={
            "kind": "equals",
            "field": "provider",
            "value": "codex",
        },
        default_index_path=lambda: index_path,
        projects_root=lambda: tmp_path / "projects",
        query_index=mock_query,
        scan_artifacts=Mock(),
    )

    assert loaded_snapshot is snapshot
    assert state.tier == "tier2"
    assert state.artifact_source == "artifact_index"
    assert state.complete_history is True
    query = mock_query.call_args.kwargs["query"]
    assert query.include_active is False
    assert query.include_recent_completed is False
    assert query.include_full_history is True
    assert query.active_limit is None
    assert query.recent_completed_limit is None
    assert query.window_limit is None
    assert query.freshness == "revalidate"
    assert query.record_shape == "list"
    assert query.candidate_filter == {
        "kind": "equals",
        "field": "provider",
        "value": "codex",
    }


def test_full_history_disabled_flag_uses_source_scan() -> None:
    snapshot = _empty_artifact_snapshot()
    mock_scan = Mock(return_value=snapshot)
    mock_index = Mock(side_effect=AssertionError("index path must stay disabled"))

    with override_flags(agents_index_full_history=False):
        loaded_snapshot, state = artifact_snapshot_for_tui_load(
            full_history=True,
            use_artifact_index=True,
            scan_artifacts=mock_scan,
            load_tier1_index=mock_index,
        )

    assert loaded_snapshot is snapshot
    assert state.artifact_source == "source_scan"
    assert state.used_artifact_index is False
    assert state.complete_history is True
    mock_scan.assert_called_once_with()


def test_full_history_missing_index_falls_back_to_source_scan(
    tmp_path: Path,
) -> None:
    snapshot = _empty_artifact_snapshot()
    mock_scan = Mock(return_value=snapshot)

    indexed = query_artifact_index_for_loader(
        full_history=True,
        default_index_path=lambda: tmp_path / "missing.sqlite",
        projects_root=lambda: tmp_path / "projects",
        query_index=Mock(side_effect=AssertionError("missing index must not query")),
        scan_artifacts=mock_scan,
    )

    assert indexed is not None
    loaded_snapshot, state = indexed
    assert loaded_snapshot is snapshot
    assert state.tier == "tier2"
    assert state.complete_history is True
    assert state.artifact_source == "source_scan"
    assert state.used_artifact_index is False
    assert state.repair_recommended is True
    assert state.repair_reason == "artifact_index_missing_full_history_fallback"
    mock_scan.assert_called_once_with()


def test_full_history_bad_index_falls_back_to_source_scan(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = _empty_artifact_snapshot()
    mock_scan = Mock(return_value=snapshot)

    indexed = query_artifact_index_for_loader(
        full_history=True,
        default_index_path=lambda: index_path,
        projects_root=lambda: tmp_path / "projects",
        query_index=Mock(side_effect=RuntimeError("stale schema")),
        scan_artifacts=mock_scan,
    )

    assert indexed is not None
    loaded_snapshot, state = indexed
    assert loaded_snapshot is snapshot
    assert state.tier == "tier2"
    assert state.complete_history is True
    assert state.artifact_source == "source_scan"
    assert state.used_artifact_index is False
    assert state.index_error == "stale schema"
    assert state.repair_recommended is True
    assert state.repair_reason == "artifact_index_query_failed_full_history_fallback"
    mock_scan.assert_called_once_with(None)


def test_full_history_busy_index_lock_falls_back_to_source_scan(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = _empty_artifact_snapshot()
    mock_scan = Mock(return_value=snapshot)

    indexed = query_artifact_index_for_loader(
        full_history=True,
        default_index_path=lambda: index_path,
        projects_root=lambda: tmp_path / "projects",
        query_index=Mock(return_value=None),
        scan_artifacts=mock_scan,
    )

    assert indexed is not None
    loaded_snapshot, state = indexed
    assert loaded_snapshot is snapshot
    assert state.tier == "tier2"
    assert state.complete_history is True
    assert state.artifact_source == "source_scan"
    assert state.used_artifact_index is False
    assert state.index_error == "artifact index operation lock busy"
    assert state.repair_recommended is False
    assert state.repair_reason == "artifact_index_lock_busy_full_history_fallback"
    mock_scan.assert_called_once_with(None)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _artifact_dir(projects: Path, timestamp: str) -> Path:
    return projects / "proj" / "artifacts" / "ace-run" / timestamp


def test_windowed_loader_keeps_completed_when_active_exceeds_limit(
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    for timestamp in (
        "20260827090000",
        "20260827090100",
        "20260827090200",
        "20260827090300",
        "20260827090400",
    ):
        _write_json(
            _artifact_dir(projects, timestamp) / "agent_meta.json",
            {"name": f"active-{timestamp}"},
        )
    for timestamp in ("20260827090500", "20260827090600", "20260827090700"):
        artifact_dir = _artifact_dir(projects, timestamp)
        _write_json(
            artifact_dir / "agent_meta.json",
            {"name": f"done-{timestamp}"},
        )
        _write_json(
            artifact_dir / "done.json",
            {"outcome": "completed", "name": f"done-{timestamp}"},
        )

    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, projects)

    snapshot, state = query_artifact_index_for_loader(
        full_history=False,
        freshness="cached",
        requested_limit=2,
        default_index_path=lambda: index_path,
        projects_root=lambda: projects,
        query_index=query_agent_artifact_index,
        scan_artifacts=lambda options=None: scan_agent_artifacts(projects, options),
    )

    timestamps = {record.timestamp for record in snapshot.records}
    assert timestamps == {
        "20260827090000",
        "20260827090100",
        "20260827090200",
        "20260827090300",
        "20260827090400",
        "20260827090600",
        "20260827090700",
    }
    assert "20260827090500" not in timestamps
    assert state.bounded_prefix is True
    assert state.has_more is True
    assert state.record_count == 7
    window = snapshot.index_window
    assert window is not None
    assert window.active_candidate_count == 5
    assert window.completed_candidate_count == 3
    assert window.selected_candidate_count == 7
