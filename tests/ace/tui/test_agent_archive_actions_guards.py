"""Archive action-boundary and live-action guard tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_actions import (
    ARCHIVE_LIVE_ONLY_ACTIONS,
    archive_ui_active,
    guard_archive_live_action,
)
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_actions_helpers import make_owner, open_archive


def test_guard_inactive_in_inbox() -> None:
    owner = make_owner()
    with override_flags(agents_archive_view=True):
        assert not archive_ui_active(owner)
        assert guard_archive_live_action(owner, "kill_agent") is False
        assert owner.notices == []


def test_guard_inactive_when_flag_off() -> None:
    owner = make_owner()
    open_archive(owner)
    with override_flags():
        assert not archive_ui_active(owner)
        assert guard_archive_live_action(owner, "kill_agent") is False
        assert owner.notices == []


def test_each_live_only_key_family_guarded() -> None:
    owner = make_owner()
    open_archive(owner, selected_key="u.m@r1")
    with override_flags(agents_archive_view=True):
        assert archive_ui_active(owner)
        for action in sorted(ARCHIVE_LIVE_ONLY_ACTIONS):
            owner.notices.clear()
            assert guard_archive_live_action(owner, action) is True
            assert len(owner.notices) == 1
            message, _severity = owner.notices[0]
            assert ",a" in message


def test_tab_and_tribe_guard_messages() -> None:
    owner = make_owner()
    open_archive(owner)
    expected = {
        "next_agents_tab": "Agent tabs live in the Inbox · ,a",
        "prev_agents_tab": "Agent tabs live in the Inbox · ,a",
        "pick_agents_tab": "Agent tabs live in the Inbox · ,a",
        "edit_agent_tribe": "Tribes live in the Inbox · ,a",
    }
    with override_flags(agents_archive_view=True):
        for action, message in expected.items():
            assert guard_archive_live_action(owner, action) is True
            assert owner.notices[-1][0] == message


def test_live_guard_names_archived_row() -> None:
    from sase.ace.tui.models.agent_archive_reader import ArchiveReaderRuntime

    owner = make_owner()
    open_archive(owner, selected_key="u.m@r1")
    owner._archive_reader_runtime = ArchiveReaderRuntime(
        archive_key="u.m@r1",
        hydrated_agent=SimpleNamespace(cl_name="agent-r1"),
    )
    with override_flags(agents_archive_view=True):
        assert guard_archive_live_action(owner, "kill_agent") is True
    message = owner.notices[0][0]
    assert "agent-r1 is archived" in message
    assert "restore" not in message


def test_guard_never_mutates_parked_inbox_state() -> None:
    inbox_marks = {("cl", "a", None)}
    inbox = object()
    owner = make_owner(inbox_agent=inbox)
    owner._marked_agents = set(inbox_marks)
    before_unread = set(owner._unread_completed_agent_ids)
    open_archive(owner)
    with override_flags(agents_archive_view=True):
        for action in (
            "kill_agent",
            "save_marked_agents",
            "agents_retry",
            "toggle_agent_unread",
        ):
            assert guard_archive_live_action(owner, action) is True
        assert owner._marked_agents == inbox_marks
        assert owner._unread_completed_agent_ids == before_unread
        assert owner._inbox_agent is inbox


def test_kill_entry_point_guarded() -> None:
    from sase.ace.tui.actions.agents._kill_action_flow import AgentKillActionFlowMixin

    class App(AgentKillActionFlowMixin):
        pass

    owner = make_owner()
    app = App()
    app.__dict__.update(owner.__dict__)
    open_archive(app)
    called: list[str] = []
    app._bulk_kill_marked_agents = lambda: called.append("bulk")  # type: ignore[attr-defined]
    with override_flags(agents_archive_view=True):
        app.action_kill_agent()
    assert called == []
    assert len(app.notices) == 1
    assert ",a" in app.notices[0][0]


def test_remaining_inbox_actions_are_guarded_or_use_archive_selection() -> None:
    from sase.ace.tui.actions.agents._metadata_pager import AgentMetadataPagerMixin
    from sase.ace.tui.actions.agents._panel_artifact_actions import (
        AgentArtifactFileActionMixin,
    )
    from sase.ace.tui.actions.agents._panel_detail import AgentPanelDetailMixin
    from sase.ace.tui.actions.agents._panel_tmux import AgentPanelTmuxMixin
    from sase.ace.tui.actions.agents._patch_navigation import AgentPatchNavigationMixin
    from sase.ace.tui.actions.hints._hooks import HookEditingMixin

    inbox = SimpleNamespace(cl_name="parked-inbox")
    owner = make_owner(inbox_agent=inbox)
    open_archive(owner, selected_key="banner:day:2026-10-10")
    selected_calls: list[bool] = []
    owner._get_selected_agent = lambda: selected_calls.append(True) or inbox
    with override_flags(agents_archive_view=True):
        for mixin, action in (
            (AgentMetadataPagerMixin, "action_view_agent_metadata"),
            (AgentPatchNavigationMixin, "action_jump_to_agent_patch"),
            (AgentArtifactFileActionMixin, "action_open_artifact_files"),
        ):
            app = mixin()
            app.__dict__.update(owner.__dict__)
            if mixin is AgentArtifactFileActionMixin:
                app._toggle_tracked_artifact_file_tmux_pane = lambda: False  # type: ignore[attr-defined]
            getattr(app, action)()
        assert selected_calls == []

        for mixin, action in (
            (AgentPanelTmuxMixin, "action_open_tmux"),
            (AgentPanelTmuxMixin, "action_start_tmux_mode"),
        ):
            app = mixin()
            app.__dict__.update(owner.__dict__)
            getattr(app, action)()
            assert app.notices[-1][0].endswith(",a for inbox")

        # sase-1jm.5: F forks and e opens the archived chat read-only, so a
        # banner selection warns about the missing run instead of guarding.
        from sase.ace.tui.actions.agents._fork_actions import AgentForkActionsMixin

        class ForkApp(HookEditingMixin, AgentForkActionsMixin):
            pass

        app = ForkApp()
        app.__dict__.update(owner.__dict__)
        app.action_edit_hooks()
        assert app.notices[-1][0] == "Select an archived run first"

        app = AgentPanelDetailMixin()
        app.__dict__.update(owner.__dict__)
        app.action_edit_spec()
        assert app.notices[-1][0] == "Select an archived run first"
        assert selected_calls == []


def test_tribe_and_tab_entries_guarded() -> None:
    from sase.ace.tui.actions.agents._agent_tabs_switch_strip import (
        AgentTabsSwitchStripMixin,
    )
    from sase.ace.tui.actions.agents._tribe_assignment import AgentTribeAssignmentMixin

    for mixin, action, arguments in (
        (AgentTribeAssignmentMixin, "action_edit_agent_tribe", ()),
        (AgentTabsSwitchStripMixin, "action_next_agents_tab", ()),
        (AgentTabsSwitchStripMixin, "action_prev_agents_tab", ()),
    ):
        owner = make_owner()
        app = mixin()
        app.__dict__.update(owner.__dict__)
        open_archive(app)
        with override_flags(agents_archive_view=True):
            getattr(app, action)(*arguments)
        assert len(app.notices) == 1, action
        assert ",a" in app.notices[0][0], action


def test_guard_toast_names_configured_toggle_key() -> None:
    from sase.ace.tui.keymaps import load_keymap_registry

    owner = make_owner()
    owner._keymap_registry = load_keymap_registry(
        {
            "keymaps": {
                "modes": {"leader_mode": {"keys": {"toggle_agents_archive": "x"}}}
            }
        }
    )
    open_archive(owner)
    with override_flags(agents_archive_view=True):
        assert guard_archive_live_action(owner, "kill_agent") is True
    message = owner.notices[0][0]
    assert ",x" in message
    assert ",a" not in message


def test_kill_and_edit_revert_and_quick_launch_are_guarded() -> None:
    from sase.ace.tui.actions.agent_workflow._entry_quick_launch import (
        EntryQuickLaunchMixin,
    )
    from sase.ace.tui.actions.agent_workflow._entry_relaunch import EntryRelaunchMixin
    from sase.ace.tui.actions.agents._marking_kill import AgentMarkedKillMixin
    from sase.ace.tui.actions.agents._revert import AgentRevertMixin

    inbox = SimpleNamespace(cl_name="parked-inbox")
    owner = make_owner(inbox_agent=inbox)
    open_archive(owner)
    with override_flags(agents_archive_view=True):
        cases = (
            (AgentRevertMixin, "_start_revert_selected_agent"),
            (EntryQuickLaunchMixin, "_start_agent_from_agent_quick"),
            (EntryRelaunchMixin, "_kill_and_edit_agent"),
            (AgentMarkedKillMixin, "_bulk_kill_marked_agents_and_edit"),
        )
        for mixin, method in cases:
            app = mixin()
            app.__dict__.update(owner.__dict__)
            notices: list[tuple[str, Any]] = []

            def notify(
                message: str,
                *,
                severity: str = "information",
                _notices: list[tuple[str, Any]] = notices,
            ) -> None:
                _notices.append((message, severity))

            app.notify = notify
            app._marked_agents = {("cl", "parked-inbox", None)}
            getattr(app, method)()
            assert notices, method
            assert "archived" in notices[-1][0] or ",a" in notices[-1][0]
