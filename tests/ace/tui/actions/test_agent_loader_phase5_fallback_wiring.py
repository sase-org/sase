"""Phase-5 source-scan fallback wiring tests for the agent loader."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.ace.tui.models.agent_loader import _artifact_snapshot_for_tui_load
from tests._agent_loader_helpers import _empty_artifact_snapshot


def test_load_agents_from_disk_full_history_reconciles_from_source() -> None:
    """Full-history refreshes use source artifacts so stale indexes cannot persist."""

    snapshot = _empty_artifact_snapshot()

    with (
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
        result = load_agents_from_disk_with_state(set(), full_history=True)

    assert result.load_state.complete_history is True
    assert result.load_state.complete_visible_inbox is True
    assert result.load_state.artifact_source == "source_scan"
    assert result.load_state.used_artifact_index is False
    mock_query.assert_not_called()
    mock_scan.assert_called_once()


def test_load_agents_from_disk_missing_index_uses_bounded_tier1_source_scan(
    tmp_path,
) -> None:
    """Missing artifact indexes do not force a full source scan before first paint."""

    index_path = tmp_path / "missing_agent_artifact_index.sqlite"
    snapshot = _empty_artifact_snapshot()

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
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

    assert result.load_state.tier == "tier1"
    assert result.load_state.complete_history is False
    assert result.load_state.complete_visible_inbox is False
    assert result.load_state.artifact_source == "source_scan"
    assert result.load_state.repair_recommended is True
    assert result.load_state.repair_reason == "artifact_index_missing_bounded_fallback"
    options = mock_scan.call_args.args[0]
    assert options.max_records == 200
    assert options.newest_first is True


def test_load_agents_from_disk_bad_index_uses_bounded_tier1_source_scan(
    tmp_path: Path,
) -> None:
    """Unreadable or stale indexes fall back without scanning full history."""

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
            side_effect=RuntimeError("stale schema"),
        ),
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

    assert result.load_state.tier == "tier1"
    assert result.load_state.complete_history is False
    assert result.load_state.complete_visible_inbox is False
    assert result.load_state.artifact_source == "source_scan"
    assert result.load_state.used_artifact_index is False
    assert result.load_state.index_error == "stale schema"
    assert result.load_state.repair_recommended is True
    assert (
        result.load_state.repair_reason
        == "artifact_index_query_failed_bounded_fallback"
    )
    options = mock_scan.call_args.args[0]
    assert options.max_records == 200
    assert options.newest_first is True


def test_explicit_index_bypass_uses_bounded_scan_without_repair_reaction() -> None:
    snapshot = _empty_artifact_snapshot()

    with (
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            side_effect=AssertionError("bypassed index must not be queried"),
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=snapshot,
        ) as mock_scan,
    ):
        loaded_snapshot, state = _artifact_snapshot_for_tui_load(
            full_history=False,
            use_artifact_index=False,
        )

    assert loaded_snapshot is snapshot
    assert state.artifact_source == "source_scan"
    assert state.complete_visible_inbox is False
    assert state.used_artifact_index is False
    assert state.repair_recommended is False
    options = mock_scan.call_args.args[0]
    assert options.max_records == 200
    assert options.newest_first is True
