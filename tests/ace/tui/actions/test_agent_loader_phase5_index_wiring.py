"""Phase-5 artifact-index wiring tests for the agent loader."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.ace.tui.models.agent_loader import _artifact_snapshot_for_tui_load
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from tests._agent_loader_helpers import _empty_artifact_snapshot


def _make_artifact_record(index: int) -> AgentArtifactRecordWire:
    timestamp = f"20260519{index % 1000000:06d}"
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir="/tmp/projects/proj",
        project_file="/tmp/projects/proj/proj.gp",
        workflow_dir_name="ace-run",
        artifact_dir=f"/tmp/projects/proj/artifacts/ace-run/{timestamp}",
        timestamp=timestamp,
    )


def test_load_agents_from_disk_uses_artifact_index_for_initial_tier(
    tmp_path,
) -> None:
    """Initial TUI loads query the artifact index instead of scanning history."""

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = _empty_artifact_snapshot()

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            return_value=snapshot,
        ) as mock_query,
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=snapshot,
        ) as mock_scan,
        patch(
            "sase.ace.tui.models.agent_loader.find_all_patches",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
    ):
        result = load_agents_from_disk_with_state(set())

    assert result.all_agents == []
    assert result.load_state.used_artifact_index is True
    assert result.load_state.complete_history is False
    assert result.load_state.complete_visible_inbox is True
    assert result.load_state.needs_full_history_reconcile is False
    mock_query.assert_called_once()
    mock_scan.assert_not_called()
    query = mock_query.call_args.kwargs["query"]
    assert query.include_active is True
    assert query.include_recent_completed is True
    assert query.include_full_history is False
    assert query.active_limit == 1000
    assert query.recent_completed_limit == 200
    assert query.include_hidden is False
    assert query.freshness == "cached"
    assert query.record_shape == "list"


def test_tier1_large_index_result_does_not_fan_out_to_source_scan(
    tmp_path: Path,
) -> None:
    """Tier 1 keeps filesystem fan-out behind the index query boundary."""

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = _empty_artifact_snapshot()
    snapshot.records.extend(_make_artifact_record(i) for i in range(10_000))

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            return_value=snapshot,
        ) as mock_query,
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
        ) as mock_scan,
    ):
        loaded_snapshot, load_state = _artifact_snapshot_for_tui_load(
            full_history=False
        )

    assert loaded_snapshot is snapshot
    assert len(loaded_snapshot.records) == 10_000
    assert load_state.artifact_source == "artifact_index"
    assert load_state.used_artifact_index is True
    assert load_state.complete_visible_inbox is True
    assert load_state.complete_history is False
    assert load_state.needs_full_history_reconcile is False
    assert load_state.record_count == 10_000
    mock_query.assert_called_once()
    mock_scan.assert_not_called()


def test_tier1_index_revalidate_mode_reaches_query_wire(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = _empty_artifact_snapshot()
    snapshot.records.append(_make_artifact_record(1))

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            return_value=snapshot,
        ) as mock_query,
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
        ) as mock_scan,
    ):
        loaded_snapshot, load_state = _artifact_snapshot_for_tui_load(
            full_history=False,
            index_freshness="revalidate",
        )

    assert loaded_snapshot is snapshot
    assert load_state.artifact_source == "artifact_index"
    mock_query.assert_called_once()
    assert mock_query.call_args.kwargs["query"].freshness == "revalidate"
    assert mock_query.call_args.kwargs["query"].record_shape == "list"
    mock_scan.assert_not_called()
