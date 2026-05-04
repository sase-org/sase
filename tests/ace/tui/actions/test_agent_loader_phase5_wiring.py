"""Phase-5 wiring tests for the agent loader.

Verifies that ``load_agents_from_disk`` accepts a pre-fetched ChangeSpec
snapshot and forwards it through to ``load_all_agents`` so the loader
does not call ``find_all_changespecs()`` itself.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk,
    load_agents_from_disk_with_state,
)
from tests._agent_loader_helpers import _empty_artifact_snapshot


def _make_snapshot() -> list[ChangeSpec]:
    return [
        ChangeSpec(
            name="my_cl",
            description="",
            parent=None,
            cl=None,
            status="WIP",
            test_targets=None,
            kickstart=None,
            file_path="/tmp/proj.gp",
            line_number=1,
        )
    ]


def test_load_agents_from_disk_passes_snapshot_through() -> None:
    snapshot = _make_snapshot()

    with (
        patch("sase.ace.tui.models.agent_loader.find_all_changespecs") as mock_find,
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
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
            "sase.ace.tui.models.agent_loader.get_workflow_timestamp_dirs",
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
        patch(
            "sase.ace.agent_tags.load_agent_tags",
            return_value={},
        ),
        patch(
            "sase.ace.tui.actions.agents._snapshot_cache.AgentSnapshotCache"
            ".dismissed_bundles",
            return_value=[],
        ),
    ):
        load_agents_from_disk(set(), changespec_snapshot=snapshot)

    mock_find.assert_not_called()


def test_load_agents_from_disk_falls_back_to_find_all() -> None:
    with (
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[],
        ) as mock_find,
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
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
            "sase.ace.tui.models.agent_loader.get_workflow_timestamp_dirs",
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
        patch(
            "sase.ace.agent_tags.load_agent_tags",
            return_value={},
        ),
        patch(
            "sase.ace.tui.actions.agents._snapshot_cache.AgentSnapshotCache"
            ".dismissed_bundles",
            return_value=[],
        ),
    ):
        load_agents_from_disk(set())

    mock_find.assert_called_once()


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
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
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
        patch("sase.ace.agent_tags.load_agent_tags", return_value={}),
    ):
        result = load_agents_from_disk_with_state(set())

    assert result.all_agents == []
    assert result.load_state.used_artifact_index is True
    assert result.load_state.complete_history is False
    mock_query.assert_called_once()
    mock_scan.assert_not_called()


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
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
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
        patch("sase.ace.agent_tags.load_agent_tags", return_value={}),
    ):
        result = load_agents_from_disk_with_state(set(), full_history=True)

    assert result.load_state.complete_history is True
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
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
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
        patch("sase.ace.agent_tags.load_agent_tags", return_value={}),
    ):
        result = load_agents_from_disk_with_state(set())

    assert result.load_state.tier == "tier1"
    assert result.load_state.complete_history is False
    assert result.load_state.artifact_source == "source_scan"
    options = mock_scan.call_args.args[0]
    assert options.max_records == 200
    assert options.newest_first is True
