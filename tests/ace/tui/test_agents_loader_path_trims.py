"""Regressions for avoidable work on the Agents loader path."""

from __future__ import annotations

from unittest.mock import Mock, patch

from sase.ace.tui.actions.agents._loading_helpers import (
    _apply_loaded_agent_disk_projections,
)
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState
from tests._dismissed_agents_helpers import make_agent


def test_done_agents_do_not_resolve_artifact_dirs() -> None:
    agent = make_agent(agent_type=AgentType.RUNNING, status="DONE")
    agent.get_artifacts_dir = Mock(side_effect=AssertionError("unexpected lookup"))  # type: ignore[method-assign]
    load_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )

    with (
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
        patch(
            "sase.ace.tui.actions.agents._snapshot_cache.get_global_snapshot_cache",
            return_value=Mock(),
        ),
    ):
        result = _apply_loaded_agent_disk_projections(
            [agent], set(), frozenset(), load_state
        )

    agent.get_artifacts_dir.assert_not_called()  # type: ignore[attr-defined]
    assert result.all_agents == [agent]
