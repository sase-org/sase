from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from sase.ace.tui.models._agent_loader_artifacts import (
    artifact_snapshot_for_tui_load,
    query_artifact_index_for_loader,
)
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.core.agent_scan_wire import AgentArtifactIndexCompletenessWire
from tests._agent_loader_helpers import _empty_artifact_snapshot


def test_full_history_uses_revalidated_artifact_index() -> None:
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
    snapshot = replace(
        _empty_artifact_snapshot(),
        index_completeness=AgentArtifactIndexCompletenessWire(
            complete_history=True,
            source_reconciled=True,
        ),
    )
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
    assert query.agents_list_projection is True
    assert query.candidate_filter == {
        "kind": "equals",
        "field": "provider",
        "value": "codex",
    }


def test_full_history_incomplete_index_result_falls_back_to_source_scan(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    indexed_snapshot = replace(
        _empty_artifact_snapshot(),
        index_completeness=AgentArtifactIndexCompletenessWire(
            complete_history=False,
            source_reconciled=False,
        ),
    )
    source_snapshot = _empty_artifact_snapshot()
    mock_scan = Mock(return_value=source_snapshot)

    loaded_snapshot, state = query_artifact_index_for_loader(
        full_history=True,
        default_index_path=lambda: index_path,
        projects_root=lambda: tmp_path / "projects",
        query_index=Mock(return_value=indexed_snapshot),
        scan_artifacts=mock_scan,
    )

    assert loaded_snapshot is source_snapshot
    assert state.tier == "tier2"
    assert state.complete_history is True
    assert state.artifact_source == "source_scan"
    assert state.used_artifact_index is False
    assert state.repair_reason == "artifact_index_incomplete_full_history_fallback"
    mock_scan.assert_called_once_with()


def test_full_history_facade_rejects_incomplete_index_state() -> None:
    indexed_snapshot = _empty_artifact_snapshot()
    source_snapshot = _empty_artifact_snapshot()
    mock_scan = Mock(return_value=source_snapshot)
    mock_load_index = Mock(
        return_value=(
            indexed_snapshot,
            AgentLoadState(
                tier="tier2",
                complete_history=False,
                artifact_source="artifact_index",
                used_artifact_index=True,
            ),
        )
    )

    loaded_snapshot, state = artifact_snapshot_for_tui_load(
        full_history=True,
        use_artifact_index=True,
        scan_artifacts=mock_scan,
        load_tier1_index=mock_load_index,
    )

    assert loaded_snapshot is source_snapshot
    assert state.tier == "tier2"
    assert state.complete_history is True
    assert state.artifact_source == "source_scan"
    assert state.used_artifact_index is False
    mock_load_index.assert_called_once()
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
