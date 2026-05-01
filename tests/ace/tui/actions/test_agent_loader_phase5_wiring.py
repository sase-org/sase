"""Phase-5 wiring tests for the agent loader.

Verifies that ``load_agents_from_disk`` accepts a pre-fetched ChangeSpec
snapshot and forwards it through to ``load_all_agents`` so the loader
does not call ``find_all_changespecs()`` itself.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.actions.agents._loading_helpers import load_agents_from_disk
from sase.core.agent_compose_wire import ComposedAgentListWire
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
            "sase.core.agent_compose_facade.compose_agent_list",
            return_value=ComposedAgentListWire(),
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
            "sase.core.agent_compose_facade.compose_agent_list",
            return_value=ComposedAgentListWire(),
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
