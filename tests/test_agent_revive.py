"""Tests for ``_do_revive_agent`` / ``_do_revive_agents`` core behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup

from tests._agent_revive_helpers import FakeReviveApp, make_agent


def test_repair_dismissed_projection_after_save() -> None:
    """Archive index repair refreshes the Tier 1 dismissed projection."""
    app = FakeReviveApp()
    archived = make_agent(cl_name="archived", raw_suffix="20260201101010")
    stale = make_agent(cl_name="stale", raw_suffix="20260202101010")
    app._dismissed_agents = {stale.identity}

    with (
        patch(
            "sase.ace.dismissed_agents.load_dismissed_bundle_identities",
            return_value={archived.identity},
        ),
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
        patch(
            "sase.ace.tui.actions.agents._revive.sync_dismissed_agent_artifact_index"
        ) as mock_sync_index,
    ):
        app._repair_dismissed_projection()

    assert app._dismissed_agents == {archived.identity}
    mock_save.assert_called_once_with(app._dismissed_agents)
    mock_sync_index.assert_called_once_with(app._dismissed_agents, force=True)


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
        patch(
            "sase.ace.tui.actions.agents._revive.sync_dismissed_agent_artifact_index"
        ) as mock_sync_index,
        patch(
            "sase.ace.tui.actions.agents._revive.upsert_agent_artifact_index_artifacts"
        ) as mock_upsert_index,
    ):
        delta = app._do_revive_agent(parent)

    assert app._dismissed_agents == {(AgentType.WORKFLOW, "keep_me", "20260202101010")}
    assert delta.revived_identities == (parent.identity, child.identity)
    assert delta.revived_artifact_dirs == (parent.artifacts_dir, parent.artifacts_dir)
    assert not delta.failed
    assert delta.generation_changed
    assert delta.has_changes
    mock_mark.assert_called_once_with({"20260201101010", "child_suffix_1"})
    mock_sync_index.assert_called_once_with(app._dismissed_agents, added=())
    mock_upsert_index.assert_called_once_with(
        [parent.artifacts_dir, parent.artifacts_dir]
    )
    assert app.load_count == 1
    assert app.delta_refresh_count == 1
    assert len(app.restored) == 2
    assert app.restored[0] == (parent.identity, None)
    assert app.restored[1] == (child.identity, parent.artifacts_dir)


def test_do_revive_agent_resolves_parent_artifact_dir_for_child_restore() -> None:
    app = FakeReviveApp()
    parent = make_agent(
        cl_name="feature",
        raw_suffix="20260201101010",
        artifacts_dir="/tmp/projects/myproj/artifacts/ace-run/20260201101010",
    )
    child = make_agent(
        cl_name="child_step",
        raw_suffix="child_suffix_1",
        parent_workflow="wf",
        parent_timestamp="20260201101010",
    )
    resolved = Path("/tmp/projects/myproj/artifacts/ace-run/202602/01/20260201101010")
    app._dismissed_agent_objects = [parent, child]
    app._dismissed_agents = {parent.identity, child.identity}

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"),
        patch(
            "sase.ace.tui.actions.agents._revive_execution.resolve_agent_artifact_path",
            return_value=resolved,
        ),
        patch(
            "sase.ace.tui.actions.agents._revive_helpers.resolve_agent_artifact_path",
            return_value=resolved,
        ),
        patch(
            "sase.ace.tui.actions.agents._revive.upsert_agent_artifact_index_artifacts"
        ) as mock_upsert_index,
    ):
        app._do_revive_agent(parent)

    assert app.restored[1] == (child.identity, str(resolved))
    mock_upsert_index.assert_called_once_with([str(resolved), str(resolved)])


def test_do_revive_agent_selects_revived_agent_panel_after_reload() -> None:
    """Single revive moves focus to the revived agent's rendered tribe panel."""
    app = FakeReviveApp()
    active = make_agent(cl_name="active", raw_suffix="active_suffix", tribe="alpha")
    dismissed = make_agent(cl_name="revived", raw_suffix="revived_suffix", tribe="beta")
    reloaded = make_agent(
        cl_name="revived",
        raw_suffix="revived_suffix",
        tribe="beta",
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
    assert app.refresh_calls == [False]


def test_do_revive_agent_blocks_non_revivable_archive() -> None:
    app = FakeReviveApp()
    dismissed = make_agent(
        cl_name="revived",
        raw_suffix="revived_suffix",
        durably_revivable=False,
        missing_requirements=["commits"],
    )
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
        patch(
            "sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"
        ) as mock_mark,
    ):
        delta = app._do_revive_agent(dismissed)

    assert delta.failed[0].stage == "capability_check"
    assert delta.failed[0].message == (
        "This archive record is not revivable: missing commits"
    )
    assert not delta.has_changes
    assert app.notifications == [
        ("This archive record is not revivable: missing commits", "warning")
    ]
    mock_save.assert_not_called()
    mock_mark.assert_not_called()


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
    assert app.refresh_calls == [False]


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


def test_do_revive_agents_batch_skips_non_revivable_archive() -> None:
    app = FakeReviveApp()
    one = make_agent(cl_name="rev1", raw_suffix="suffix1")
    two = make_agent(
        cl_name="rev2",
        raw_suffix="suffix2",
        durably_revivable=False,
        missing_requirements=["loader_reconstructible_archive"],
    )
    app._dismissed_agent_objects = [one, two]
    app._dismissed_agents = {one.identity, two.identity}

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch(
            "sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"
        ) as mock_mark,
    ):
        delta = app._do_revive_agents([one, two])

    assert delta is not False
    assert delta.revived_identities == (one.identity,)
    assert len(delta.failed) == 1
    assert delta.failed[0].identity == two.identity
    assert delta.failed[0].stage == "capability_check"
    assert delta.failed[0].message == (
        "This archive record is not revivable: missing loader_reconstructible_archive"
    )
    mock_mark.assert_called_once_with({"suffix1"})


def test_do_revive_agent_uses_artifact_delta_for_known_dir() -> None:
    """Revive reconciles a restored known artifact dir without full history."""
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
    assert app.delta_refresh_count == 1
    assert app.last_load_full_history is False


def test_do_revive_agents_batch_uses_artifact_delta_for_known_dirs() -> None:
    """Batch revive reconciles restored known artifact dirs without full history."""
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
    assert app.delta_refresh_count == 1
    assert app.last_load_full_history is False


def test_do_revive_agent_skips_agents_tab_refilter_from_artifacts_tab() -> None:
    """Artifacts Agent pane consumes the delta without mutating Agents tab selection."""
    app = FakeReviveApp()
    app.current_tab = "artifacts"
    dismissed = make_agent(cl_name="revived", raw_suffix="revived_suffix")
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"),
    ):
        delta = app._do_revive_agent(dismissed)

    assert delta.revived_identities == (dismissed.identity,)
    assert delta.has_changes
    assert app.refilter_count == 0
    assert app.refresh_calls == []


def test_do_revive_agents_delta_records_partial_artifact_restore_failure() -> None:
    app = FakeReviveApp()
    one = make_agent(cl_name="rev1", raw_suffix="suffix1")
    two = make_agent(cl_name="rev2", raw_suffix="suffix2")
    app._dismissed_agent_objects = [one, two]
    app._dismissed_agents = {one.identity, two.identity}

    def restore(agent: object, *, parent_artifacts_dir: str | None = None) -> None:
        del parent_artifacts_dir
        if agent is two:
            raise RuntimeError("missing bundle")
        app.restored.append((one.identity, None))

    app._restore_agent_artifacts = restore  # type: ignore[method-assign]

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"),
    ):
        delta = app._do_revive_agents([one, two])

    assert delta is not False
    assert delta.revived_identities == (one.identity,)
    assert len(delta.failed) == 1
    assert delta.failed[0].identity == two.identity
    assert delta.failed[0].stage == "artifact_restore"
    assert delta.has_changes


def test_do_revive_agent_missing_artifact_dir_falls_back_to_full_history() -> None:
    """Revive still uses full-history recovery when restored dirs are unknown."""
    app = FakeReviveApp()
    dismissed = make_agent(cl_name="revived", raw_suffix="revived_suffix")
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"),
        patch(
            "sase.ace.tui.actions.agents._revive.upsert_agent_artifact_index_artifacts"
        ),
        patch(
            "sase.ace.tui.actions.agents._revive_execution.revived_artifact_dir",
            return_value=None,
        ),
    ):
        app._do_revive_agent(dismissed)

    assert app.load_count == 1
    assert app.delta_refresh_count == 0
    assert app.last_load_full_history is True


def test_do_revive_agents_batch_selects_first_selected_parent() -> None:
    """Batch revive selects the first selected parent, not an implicit child."""
    app = FakeReviveApp()
    active = make_agent(cl_name="active", raw_suffix="active_suffix", tribe="alpha")
    parent_one = make_agent(
        cl_name="feature1",
        raw_suffix="parent_one_suffix",
        tribe="beta",
    )
    parent_two = make_agent(
        cl_name="feature2",
        raw_suffix="parent_two_suffix",
        workflow="wf_two",
        tribe="gamma",
    )
    child_one = make_agent(
        cl_name="child1",
        raw_suffix="child_one_suffix",
        parent_workflow="wf",
        parent_timestamp="parent_one_suffix",
        tribe="beta",
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
    assert app.refresh_calls == [False]
