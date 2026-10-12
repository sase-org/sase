"""Action-boundary tests: live guards, Archive marks, footer, and help.

Proves the Archive action isolation for child epic ``sase-1jm.3.1``: every
live-only key family toasts and no-ops while the Archive owns the panel,
Archive ``m``/``u`` marks live on stable identities apart from Inbox marks,
readers resolve the hydrated Archive agent, the footer stays conditional and
live-free, and the help box documents the read-only surface. Beta-off cases
prove the Inbox keeps its existing behavior.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_actions import (
    ARCHIVE_LIVE_ONLY_ACTIONS,
    _archive_guard_message,
    archive_markable_key,
    archive_marked_count,
    archive_marked_run_keys,
    archive_read_target,
    archive_ui_active,
    clear_archive_marks,
    guard_archive_live_action,
    resolve_agents_read_agent,
    toggle_archive_mark,
)
from sase.ace.tui.widgets._keybinding_bindings_agents import AgentBindingsMixin
from sase.ace.tui.actions.agents._archive_view import (
    get_agents_tab_selection,
    init_agents_archive_view_state,
)
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    ARCHIVE_SECTION_LIST,
    ARCHIVE_SECTION_PULSE,
)
from sase.feature_flags import override_flags


def _owner(*, inbox_agent: Any = None) -> SimpleNamespace:
    owner = SimpleNamespace()
    owner.current_tab = "agents"
    owner.current_idx = 0
    owner.notices: list[tuple[str, Any]] = []
    owner._marked_agents = set()
    owner._unread_completed_agent_ids = {"some:live:identity"}
    owner._inbox_agent = inbox_agent

    def notify(message: str, *, severity: str = "information") -> None:
        owner.notices.append((message, severity))

    def get_selected_agent() -> Any:
        return owner._inbox_agent

    owner.notify = notify
    owner._get_selected_agent = get_selected_agent
    init_agents_archive_view_state(owner)
    return owner


def _open_archive(
    owner: SimpleNamespace, *, selected_key: str | None = "u.m@r1"
) -> None:
    owner._agents_archive_view.active_view = AGENTS_VIEW_ARCHIVE
    owner._agents_archive_view.generation += 1
    owner._agents_archive_view.archive.selected_key = selected_key
    owner._agents_archive_view.archive.focused_section = ARCHIVE_SECTION_LIST


def test_guard_inactive_in_inbox() -> None:
    owner = _owner()
    with override_flags(agents_archive_view=True):
        assert not archive_ui_active(owner)
        assert guard_archive_live_action(owner, "kill_agent") is False
        assert owner.notices == []


def test_guard_inactive_when_flag_off() -> None:
    owner = _owner()
    _open_archive(owner)
    with override_flags():
        assert not archive_ui_active(owner)
        assert guard_archive_live_action(owner, "kill_agent") is False
        assert owner.notices == []


def test_each_live_only_key_family_guarded() -> None:
    owner = _owner()
    _open_archive(owner, selected_key="u.m@r1")
    with override_flags(agents_archive_view=True):
        assert archive_ui_active(owner)
        for action in sorted(ARCHIVE_LIVE_ONLY_ACTIONS):
            owner.notices.clear()
            assert guard_archive_live_action(owner, action) is True
            assert len(owner.notices) == 1
            message, _severity = owner.notices[0]
            assert ",a" in message


def test_tab_and_tribe_guard_messages() -> None:
    assert (
        _archive_guard_message("next_agents_tab") == "Agent tabs live in the Inbox · ,a"
    )
    assert (
        _archive_guard_message("prev_agents_tab") == "Agent tabs live in the Inbox · ,a"
    )
    assert (
        _archive_guard_message("pick_agents_tab") == "Agent tabs live in the Inbox · ,a"
    )
    assert _archive_guard_message("edit_agent_tribe") == "Tribes live in the Inbox · ,a"


def test_live_guard_names_archived_row() -> None:
    owner = _owner()
    _open_archive(owner, selected_key="u.m@r1")
    with override_flags(agents_archive_view=True):
        message = _archive_guard_message("kill_agent", target_name="agent-r1")
        assert "agent-r1 is archived" in message
        assert "restore" not in message


def test_guard_never_mutates_parked_inbox_state() -> None:
    inbox_marks = {("cl", "a", None)}
    inbox = object()
    owner = _owner(inbox_agent=inbox)
    owner._marked_agents = set(inbox_marks)
    before_unread = set(owner._unread_completed_agent_ids)
    _open_archive(owner)
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

    owner = _owner()
    app = App()
    app.__dict__.update(owner.__dict__)
    _open_archive(app)
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
    owner = _owner(inbox_agent=inbox)
    _open_archive(owner, selected_key="banner:day:2026-10-10")
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
            (HookEditingMixin, "action_edit_hooks"),
            (AgentPanelDetailMixin, "action_edit_spec"),
            (AgentPanelTmuxMixin, "action_open_tmux"),
            (AgentPanelTmuxMixin, "action_start_tmux_mode"),
        ):
            app = mixin()
            app.__dict__.update(owner.__dict__)
            getattr(app, action)()
            assert app.notices[-1][0].endswith(",a for inbox")


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
        owner = _owner()
        app = mixin()
        app.__dict__.update(owner.__dict__)
        _open_archive(app)
        with override_flags(agents_archive_view=True):
            getattr(app, action)(*arguments)
        assert len(app.notices) == 1, action
        assert ",a" in app.notices[0][0], action


def test_toggle_mark_routes_to_archive_marks(monkeypatch: Any) -> None:
    from sase.ace.tui.actions.marking import MarkingMixin

    owner = _owner()
    app = MarkingMixin()
    app.__dict__.update(owner.__dict__)
    _open_archive(app, selected_key="u.m@r1")
    refreshed: list[bool] = []
    footer_refreshed: list[bool] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._archive_column.refresh_column",
        lambda _owner, **_kwargs: refreshed.append(True),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._archive_column.refresh_archive_footer",
        lambda _owner: footer_refreshed.append(True),
    )
    with override_flags(agents_archive_view=True):
        app.action_toggle_mark()
    assert app._agents_archive_view.archive.marks == frozenset({"u.m@r1"})
    assert app._marked_agents == set()
    assert refreshed == [True]
    assert footer_refreshed == [True]


def test_mark_banner_tail_pulse_rejected() -> None:
    owner = _owner()
    with override_flags(agents_archive_view=True):
        _open_archive(owner, selected_key="banner:day:2026-10-10")
        assert toggle_archive_mark(owner) is False
        _open_archive(owner, selected_key="tail:day:2026-10-10")
        assert toggle_archive_mark(owner) is False
        _open_archive(owner, selected_key="u.m@r1")
        owner._agents_archive_view.archive.focused_section = ARCHIVE_SECTION_PULSE
        assert archive_markable_key(owner) is None
        assert toggle_archive_mark(owner) is False
        assert archive_marked_count(owner) == 0


def test_archive_marks_independent_from_inbox_marks() -> None:
    owner = _owner()
    owner._marked_agents = {("cl", "live", None)}
    _open_archive(owner, selected_key="u.m@r1")
    with override_flags(agents_archive_view=True):
        assert toggle_archive_mark(owner) is True
        assert toggle_archive_mark(owner) is True
        assert owner._agents_archive_view.archive.marks == frozenset()
        assert toggle_archive_mark(owner) is True
        assert owner._marked_agents == {("cl", "live", None)}
        assert archive_marked_count(owner) == 1
        assert clear_archive_marks(owner) == 1
        assert archive_marked_count(owner) == 0
        assert owner._marked_agents == {("cl", "live", None)}


def test_archive_marks_parked_with_view_state() -> None:
    owner = _owner()
    _open_archive(owner, selected_key="u.m@r1")
    with override_flags(agents_archive_view=True):
        assert toggle_archive_mark(owner) is True
    with override_flags():
        assert archive_marked_count(owner) == 0
        assert clear_archive_marks(owner) == 0


def _column_owner_with_members() -> SimpleNamespace:
    from sase.ace.tui.models.agent_archive_list import (
        ITEM_CONTAINER,
        ITEM_MEMBER,
    )

    owner = _owner()
    _open_archive(owner, selected_key="container:archive:u.m@clan1")
    member_rows = [
        {
            "archive_key": {
                "source_username": "u",
                "source_machine": "m",
                "source_run_id": "m1",
            },
            "container_key": "archive:u.m@clan1",
            "agent_name": "swarm.one",
        },
        {
            "archive_key": {
                "source_username": "u",
                "source_machine": "m",
                "source_run_id": "m2",
            },
            "container_key": "archive:u.m@clan1",
            "agent_name": "swarm.two",
        },
    ]
    items = [
        SimpleNamespace(kind=ITEM_CONTAINER, member_of=None, row=None),
        *(
            SimpleNamespace(kind=ITEM_MEMBER, member_of="archive:u.m@clan1", row=row)
            for row in member_rows
        ),
    ]
    from sase.ace.tui.actions.agents._archive_column import _ColumnRuntime

    runtime = _ColumnRuntime()
    runtime.model = SimpleNamespace(items=items)  # type: ignore[assignment]
    owner._archive_column_runtime = runtime
    return owner


def test_marked_run_keys_expand_containers() -> None:
    owner = _column_owner_with_members()
    with override_flags(agents_archive_view=True):
        assert toggle_archive_mark(owner) is True
        expanded = archive_marked_run_keys(owner)
    assert "container:archive:u.m@clan1" in expanded
    assert "u.m@m1" in expanded
    assert "u.m@m2" in expanded


def test_marked_run_keys_exclude_inbox_identities() -> None:
    owner = _column_owner_with_members()
    owner._marked_agents = {("cl", "live", None)}
    with override_flags(agents_archive_view=True):
        assert toggle_archive_mark(owner) is True
        expanded = archive_marked_run_keys(owner)
    assert ("cl", "live", None) not in expanded  # type: ignore[comparison-overlap]
    assert all(isinstance(key, str) for key in expanded)


def test_read_target_none_outside_archive() -> None:
    owner = _owner(inbox_agent=SimpleNamespace(cl_name="live"))
    with override_flags(agents_archive_view=True):
        assert archive_read_target(owner) is None
        assert resolve_agents_read_agent(owner) is owner._inbox_agent


def test_read_target_none_for_nav_items() -> None:
    owner = _owner(inbox_agent=SimpleNamespace(cl_name="live"))
    with override_flags(agents_archive_view=True):
        _open_archive(owner, selected_key="banner:day:2026-10-10")
        selection = get_agents_tab_selection(owner)
        assert selection.row_kind == "none"
        assert archive_read_target(owner) is None
        assert resolve_agents_read_agent(owner) is None


def test_copy_context_resolves_without_raise() -> None:
    from sase.ace.tui.actions.clipboard._palette import _build_agent_context

    owner = _owner()
    with override_flags(agents_archive_view=True):
        _open_archive(owner, selected_key="banner:day:2026-10-10")
        assert _build_agent_context(owner) is None


def _bindings_for_owner(owner: SimpleNamespace) -> list[tuple[str, str]]:
    """Compute footer bindings from live Archive state, like the footer does."""
    from sase.ace.tui.models.agent_archive_view import is_archive_container_key

    key = archive_markable_key(owner)
    mixin = AgentBindingsMixin()
    mixin._kd = lambda name: name  # type: ignore[attr-defined]
    return mixin._compute_archive_bindings(
        marked_count=archive_marked_count(owner),
        has_selection=key is not None,
        selection_is_container=bool(key and is_archive_container_key(key)),
    )


def test_archive_footer_bindings_selection() -> None:
    owner = _owner()
    with override_flags(agents_archive_view=True):
        _open_archive(owner, selected_key="u.m@r1")
        bindings = _bindings_for_owner(owner)
    assert ("toggle_mark", "mark") in bindings
    assert not any(action == "act_on_agent" for action, _label in bindings)
    assert not any("kill" in label or "Inbox" in label for _key, label in bindings)


def test_archive_footer_bindings_empty_without_selection() -> None:
    owner = _owner()
    with override_flags(agents_archive_view=True):
        _open_archive(owner, selected_key=None)
        assert _bindings_for_owner(owner) == []


def test_archive_footer_bindings_container_and_marks() -> None:
    owner = _column_owner_with_members()
    with override_flags(agents_archive_view=True):
        assert toggle_archive_mark(owner) is True
        bindings = _bindings_for_owner(owner)
    labels = [label for _key, label in bindings]
    assert "expand" in labels
    assert "unmark (1)" in labels


def test_compute_archive_bindings_has_no_live_chips() -> None:
    from sase.ace.tui.widgets._keybinding_bindings_agents import AgentBindingsMixin

    mixin = AgentBindingsMixin()
    mixin._kd = lambda name: name  # type: ignore[attr-defined]
    bindings = mixin._compute_archive_bindings(
        marked_count=2,
        has_selection=True,
        selection_is_container=True,
        deck_card_count=3,
        card_blocks_navigable=True,
        deck_view_cycle_available=True,
    )
    text = " ".join(f"{key} {label}" for key, label in bindings)
    for live in ("kill", "wait", "retry", "cleanup", "tabs", "Inbox", "restore"):
        assert live not in text
    assert not any(action == "act_on_agent" for action, _label in bindings)


def test_availability_hides_live_actions_in_archive() -> None:
    from sase.ace.tui._app_action_availability_agents import check_agents_availability

    owner = _owner()
    _open_archive(owner)
    with override_flags(agents_archive_view=True):
        for action in ("kill_agent", "reword", "agents_retry", "edit_agent_tribe"):
            assert check_agents_availability(owner, action, ()) is True
        assert check_agents_availability(owner, "act_on_agent", ()) is None
        assert check_agents_availability(owner, "next_deck_card", ()) is None
        assert check_agents_availability(owner, "pick_deck", ()) is None


def test_command_palette_hides_live_only_actions_in_archive() -> None:
    from sase.ace.tui.commands import CommandContext, build_command_catalog
    from sase.ace.tui.commands.availability import is_command_available
    from sase.ace.tui.keymaps import load_keymap_registry

    catalog = {
        spec.id: spec for spec in build_command_catalog(load_keymap_registry({}))
    }
    live_agent = SimpleNamespace(status="RUNNING")
    context = CommandContext(tab="agents", agent=live_agent, agents_archive_active=True)
    with override_flags(agents_archive_view=True):
        assert not is_command_available(catalog["app.kill_agent"], context)


def test_availability_untouched_in_inbox() -> None:
    from sase.ace.tui._app_action_availability_agents import check_agents_availability

    owner = _owner()
    with override_flags(agents_archive_view=True):
        assert check_agents_availability(owner, "kill_agent", ()) is None


def test_help_archive_box_content() -> None:
    from sase.ace.tui.keymaps import load_keymap_registry
    from sase.ace.tui.modals.help_modal.agents_archive_sections import archive_sections
    from sase.ace.tui.modals.help_modal.agents_bindings import agents_bindings

    km = load_keymap_registry({})
    boxes = dict(archive_sections(km))
    assert "Archive (read-only)" in boxes
    rows = boxes["Archive (read-only)"]
    assert all(len(key) <= 16 for key, _description in rows)
    assert all(len(description) <= 32 for _key, description in rows)
    assert rows[0][0] == ",a"
    assert not any(
        "read archived run" == description.lower() for _, description in rows
    )
    with override_flags(agents_archive_view=True):
        full = dict(agents_bindings(km))
    assert "Archive (read-only)" in full


def test_archive_help_and_leader_label_are_hidden_with_beta_off() -> None:
    from sase.ace.tui.keymaps import load_keymap_registry
    from sase.ace.tui.modals.help_modal.agents_bindings import agents_bindings
    from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter

    km = load_keymap_registry({})
    footer = KeybindingFooter()
    footer.set_keymap_registry(km)
    with override_flags():
        assert "Archive (read-only)" not in dict(agents_bindings(km))
        footer.update_leader_bindings(current_tab="agents")
        bindings, _mode = footer._last_layout_inputs or ([], None)
        assert "toggle Archive" not in " ".join(label for _, label in bindings)
    with override_flags(agents_archive_view=True):
        footer.update_leader_bindings(current_tab="agents")
        bindings, _mode = footer._last_layout_inputs or ([], None)
        assert "toggle Archive" in " ".join(label for _, label in bindings)


def test_unread_attention_accounting_untouched() -> None:
    owner = _owner()
    before_unread = set(owner._unread_completed_agent_ids)
    _open_archive(owner, selected_key="u.m@r1")
    with override_flags(agents_archive_view=True):
        assert toggle_archive_mark(owner) is True
        assert clear_archive_marks(owner) == 1
        assert guard_archive_live_action(owner, "toggle_agent_unread") is True
    assert owner._unread_completed_agent_ids == before_unread


def test_toggle_archive_hidden_from_palette_when_beta_off() -> None:
    from sase.ace.tui.commands import CommandContext, build_command_catalog
    from sase.ace.tui.commands.availability import is_command_available
    from sase.ace.tui.keymaps import load_keymap_registry

    catalog = {
        spec.id: spec for spec in build_command_catalog(load_keymap_registry({}))
    }
    context = CommandContext(tab="agents")
    with override_flags():
        assert not is_command_available(
            catalog["leader.toggle_agents_archive"], context
        )
        assert not is_command_available(catalog["agents.open_archive"], context)
    with override_flags(agents_archive_view=True):
        assert is_command_available(catalog["leader.toggle_agents_archive"], context)


def test_command_palette_hides_every_live_only_action_in_archive() -> None:
    from sase.ace.tui.commands import CommandContext, build_command_catalog
    from sase.ace.tui.commands.availability import is_command_available
    from sase.ace.tui.keymaps import load_keymap_registry

    catalog = {
        spec.id: spec for spec in build_command_catalog(load_keymap_registry({}))
    }
    live_agent = SimpleNamespace(status="RUNNING")
    context = CommandContext(tab="agents", agent=live_agent, agents_archive_active=True)
    hidden: list[str] = []
    with override_flags(agents_archive_view=True):
        for spec in catalog.values():
            action_id = spec.id
            for prefix in ("app.", "leader."):
                if action_id.startswith(prefix):
                    action_id = action_id.removeprefix(prefix)
                    break
            if action_id in ARCHIVE_LIVE_ONLY_ACTIONS:
                assert not is_command_available(spec, context), spec.id
                hidden.append(spec.id)
        for required in (
            "app.kill_agent",
            "leader.kill_and_edit",
            "leader.revert_agent",
            "leader.agent_from_cl",
        ):
            assert required in hidden
        view_files = catalog.get("app.view_files")
        if view_files is not None and "agents" in view_files.tabs:
            assert is_command_available(view_files, context)


def test_guard_toast_names_configured_toggle_key() -> None:
    from sase.ace.tui.keymaps import load_keymap_registry

    owner = _owner()
    owner._keymap_registry = load_keymap_registry(
        {
            "keymaps": {
                "modes": {"leader_mode": {"keys": {"toggle_agents_archive": "x"}}}
            }
        }
    )
    _open_archive(owner)
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
    owner = _owner(inbox_agent=inbox)
    _open_archive(owner)
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


def test_view_files_on_banner_does_not_use_parked_inbox() -> None:
    from sase.ace.tui.actions.hints._files import FileViewingMixin

    inbox = SimpleNamespace(cl_name="parked-inbox")
    owner = _owner(inbox_agent=inbox)
    _open_archive(owner, selected_key="banner:day:2026-10-10")
    extra: dict[str, object] = {}
    app = FileViewingMixin()
    app.__dict__.update(owner.__dict__)
    app._refocus_existing_hint_bar = lambda: False  # type: ignore[attr-defined]
    with override_flags(agents_archive_view=True):
        assert resolve_agents_read_agent(app) is None
        app._view_agent_files_impl(extra)  # type: ignore[attr-defined]
    assert extra["outcome"] == "no_agent"


def test_hydrated_archive_run_is_the_read_target() -> None:
    from sase.ace.tui.models.agent_archive_reader import (
        ArchiveReaderRuntime,
        mark_agent_archive_read_only,
    )
    from tests.ace.agent_artifact_startup_fixtures import make_agent

    archived = mark_agent_archive_read_only(make_agent(cl_name="archived-run"))
    inbox = SimpleNamespace(cl_name="parked-inbox", identity=("parked",))
    owner = _owner(inbox_agent=inbox)
    _open_archive(owner, selected_key="u.m@r1")
    owner._archive_reader_runtime = ArchiveReaderRuntime(
        archive_key="u.m@r1",
        hydrated_agent=archived,
    )
    with override_flags(agents_archive_view=True):
        assert resolve_agents_read_agent(owner) is archived
        assert owner._get_selected_agent() is inbox


def test_metadata_pager_and_patch_jump_use_hydrated_archive_agent(
    monkeypatch: Any,
) -> None:
    from sase.ace.tui.actions.agents._metadata_pager import AgentMetadataPagerMixin
    from sase.ace.tui.actions.agents._patch_navigation import AgentPatchNavigationMixin
    from sase.ace.tui.models.agent_archive_reader import (
        ArchiveReaderRuntime,
        mark_agent_archive_read_only,
    )
    from tests.ace.agent_artifact_startup_fixtures import make_agent

    archived = mark_agent_archive_read_only(
        make_agent(cl_name="archived-cl", raw_suffix="20250101120000")
    )
    owner = _owner(inbox_agent=SimpleNamespace(cl_name="parked-inbox"))
    _open_archive(owner, selected_key="u.m@r1")
    owner._archive_reader_runtime = ArchiveReaderRuntime(
        archive_key="u.m@r1",
        hydrated_agent=archived,
    )
    jumped: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_actions.navigate_to_patch_tab",
        lambda _app, name, project: jumped.append((name, project)),
    )
    with override_flags(agents_archive_view=True):
        pager = AgentMetadataPagerMixin()
        pager.__dict__.update(owner.__dict__)
        pager.current_tab = "agents"
        pager.run_worker = lambda coro, **_kwargs: setattr(pager, "_worker", coro)
        pager.action_view_agent_metadata()
        assert getattr(pager, "_worker", None) is not None

        jumper = AgentPatchNavigationMixin()
        jumper.__dict__.update(owner.__dict__)
        jumper.current_tab = "agents"
        jumper._resolve_agent_cl_name = lambda agent: agent.cl_name  # type: ignore[attr-defined]
        jumper.notify = owner.notify
        jumper.action_jump_to_agent_patch()
    assert jumped == [("archived-cl", archived.project_file)]


def test_act_on_agent_routes_to_archive_activate(monkeypatch: Any) -> None:
    from sase.ace.tui.actions.agents._agent_enter_action import AgentEnterActionMixin

    routed: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._agent_enter_action.route_archive_key_if_active",
        lambda _owner, intent: routed.append(intent) or True,
    )
    owner = _owner(inbox_agent=SimpleNamespace(cl_name="parked-inbox"))
    _open_archive(owner, selected_key="u.m@r1")
    app = AgentEnterActionMixin()
    app.__dict__.update(owner.__dict__)
    app.current_tab = "agents"
    with override_flags(agents_archive_view=True):
        app.action_act_on_agent()
    assert routed == ["activate"]
