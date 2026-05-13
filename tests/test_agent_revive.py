"""Tests for ``_do_revive_agent`` / ``_do_revive_agents`` core behavior."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup

from tests._agent_revive_helpers import FakeReviveApp, make_agent


def test_do_revive_agent_removes_suffix_aliases() -> None:
    """Single revive clears all dismissed aliases for revived suffixes."""
    app = FakeReviveApp()
    parent = make_agent(cl_name="feature", raw_suffix="20260201101010")
    child = make_agent(
        cl_name="child_step",
        raw_suffix="child_suffix_1",
        parent_workflow="wf",
        parent_timestamp="20260201101010",
    )
    app._agents = [parent]
    app._dismissed_agent_objects = [parent, child]
    app._dismissed_agents = {
        parent.identity,
        child.identity,
        (AgentType.RUNNING, "alias_running", "20260201101010"),
        (AgentType.WORKFLOW, "alias_child", "child_suffix_1"),
        (AgentType.WORKFLOW, "keep_me", "20260202101010"),
    }

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch(
            "sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"
        ) as mock_mark,
    ):
        app._do_revive_agent(parent)

    assert app._dismissed_agents == {(AgentType.WORKFLOW, "keep_me", "20260202101010")}
    mock_mark.assert_called_once_with({"20260201101010", "child_suffix_1"})
    assert app.load_count == 1
    assert len(app.restored) == 2
    assert app.restored[0] == (parent.identity, None)
    assert app.restored[1] == (child.identity, parent.artifacts_dir)


def test_do_revive_agent_selects_revived_agent_panel_after_reload() -> None:
    """Single revive moves focus to the revived agent's rendered tag panel."""
    app = FakeReviveApp()
    active = make_agent(cl_name="active", raw_suffix="active_suffix", tag="alpha")
    dismissed = make_agent(cl_name="revived", raw_suffix="revived_suffix", tag="beta")
    reloaded = make_agent(
        cl_name="revived",
        raw_suffix="revived_suffix",
        tag="beta",
        status="RUNNING",
    )
    app._agents = [active]
    app.loaded_agents = [active, reloaded]
    app._panel_group = AgentPanelGroup.from_agents(app._agents, focused_key="alpha")
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}
    app.current_idx = 0
    app.current_attempt_number = 7

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"),
    ):
        app._do_revive_agent(dismissed)

    assert app.current_idx == 1
    assert app._agents[app.current_idx].raw_suffix == "revived_suffix"
    assert app._panel_group.focused_key == "beta"
    assert app._current_group_key is None
    assert app.current_attempt_number is None
    assert app.refresh_count == 1


def test_do_revive_agent_clears_stale_banner_focus() -> None:
    """Reviving an agent selects its row, not a stale collapsed group banner."""
    app = FakeReviveApp()
    dismissed = make_agent(cl_name="revived", raw_suffix="revived_suffix")
    reloaded = make_agent(cl_name="revived", raw_suffix="revived_suffix")
    app.loaded_agents = [reloaded]
    app._panel_group = AgentPanelGroup.from_agents([reloaded])
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}
    app._current_group_key = ("stale",)

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"),
    ):
        app._do_revive_agent(dismissed)

    assert app.current_idx == 0
    assert app._current_group_key is None
    assert app.refresh_count == 1


def test_do_revive_agents_batch_removes_suffix_aliases() -> None:
    """Batch revive clears aliases for all revived parent/child suffixes."""
    app = FakeReviveApp()
    parent_one = make_agent(cl_name="feature1", raw_suffix="20260201101010")
    parent_two = make_agent(
        cl_name="feature2",
        raw_suffix="20260301101010",
        workflow="wf_two",
    )
    child_one = make_agent(
        cl_name="child1",
        raw_suffix="child_suffix_1",
        parent_workflow="wf",
        parent_timestamp="20260201101010",
    )
    followup_one = make_agent(
        cl_name="feature1",
        raw_suffix="followup_suffix_1",
        parent_workflow=None,
        parent_timestamp="20260201101010",
    )
    app._dismissed_agent_objects = [parent_one, parent_two, child_one, followup_one]
    app._dismissed_agents = {
        parent_one.identity,
        parent_two.identity,
        child_one.identity,
        followup_one.identity,
        (AgentType.RUNNING, "alias_one", "20260201101010"),
        (AgentType.WORKFLOW, "alias_child", "child_suffix_1"),
        (AgentType.RUNNING, "alias_followup", "followup_suffix_1"),
        (AgentType.RUNNING, "alias_two", "20260301101010"),
        (AgentType.WORKFLOW, "keep_me", "20260401101010"),
    }

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
        patch(
            "sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"
        ) as mock_mark,
    ):
        app._do_revive_agents([parent_one, parent_two])

    assert app._dismissed_agents == {(AgentType.WORKFLOW, "keep_me", "20260401101010")}
    mock_save.assert_called_once()
    mock_mark.assert_called_once_with(
        {
            "20260201101010",
            "child_suffix_1",
            "followup_suffix_1",
            "20260301101010",
        }
    )
    assert app.load_count == 1
    assert len(app.restored) == 4


def test_do_revive_agent_forces_full_history_reload() -> None:
    """Revive must request a Tier 2 source scan, not the default Tier 1.

    A stale or empty artifact index returns zero rows for completed
    history without raising, so the reload after revive must bypass the
    index and hit source-of-truth artifacts.
    """
    app = FakeReviveApp()
    dismissed = make_agent(cl_name="revived", raw_suffix="revived_suffix")
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"),
    ):
        app._do_revive_agent(dismissed)

    assert app.load_count == 1
    assert app.last_load_full_history is True


def test_do_revive_agents_batch_forces_full_history_reload() -> None:
    """Batch revive must also force a Tier 2 source scan."""
    app = FakeReviveApp()
    one = make_agent(cl_name="rev1", raw_suffix="suffix1")
    two = make_agent(cl_name="rev2", raw_suffix="suffix2")
    app._dismissed_agent_objects = [one, two]
    app._dismissed_agents = {one.identity, two.identity}

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"),
    ):
        app._do_revive_agents([one, two])

    assert app.load_count == 1
    assert app.last_load_full_history is True


def test_do_revive_agents_batch_selects_first_selected_parent() -> None:
    """Batch revive selects the first selected parent, not an implicit child."""
    app = FakeReviveApp()
    active = make_agent(cl_name="active", raw_suffix="active_suffix", tag="alpha")
    parent_one = make_agent(
        cl_name="feature1",
        raw_suffix="parent_one_suffix",
        tag="beta",
    )
    parent_two = make_agent(
        cl_name="feature2",
        raw_suffix="parent_two_suffix",
        workflow="wf_two",
        tag="gamma",
    )
    child_one = make_agent(
        cl_name="child1",
        raw_suffix="child_one_suffix",
        parent_workflow="wf",
        parent_timestamp="parent_one_suffix",
        tag="beta",
    )
    app._agents = [active]
    app.loaded_agents = [active, child_one, parent_one, parent_two]
    app._panel_group = AgentPanelGroup.from_agents(app._agents, focused_key="alpha")
    app._dismissed_agent_objects = [parent_one, parent_two, child_one]
    app._dismissed_agents = {
        parent_one.identity,
        parent_two.identity,
        child_one.identity,
    }

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"),
    ):
        app._do_revive_agents([parent_one, parent_two])

    assert app.current_idx == 2
    assert app._agents[app.current_idx].raw_suffix == "parent_one_suffix"
    assert app._panel_group.focused_key == "beta"
    assert app._current_group_key is None
    assert app.current_attempt_number is None
    assert app.refresh_count == 1
