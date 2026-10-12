"""Archive command availability, help, and beta-flag tests."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.actions.agents._archive_actions import ARCHIVE_LIVE_ONLY_ACTIONS
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_actions_helpers import make_owner, open_archive


def test_availability_hides_live_actions_in_archive() -> None:
    from sase.ace.tui._app_action_availability_agents import check_agents_availability

    owner = make_owner()
    open_archive(owner)
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
    assert not is_command_available(catalog["app.kill_agent"], context)


def test_availability_untouched_in_inbox() -> None:
    from sase.ace.tui._app_action_availability_agents import check_agents_availability

    owner = make_owner()
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
    full = dict(agents_bindings(km))
    assert "Archive (read-only)" in full


def test_archive_help_and_leader_label_shown_without_flag() -> None:
    from sase.ace.tui.keymaps import load_keymap_registry
    from sase.ace.tui.modals.help_modal.agents_bindings import agents_bindings
    from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter

    km = load_keymap_registry({})
    footer = KeybindingFooter()
    footer.set_keymap_registry(km)
    with override_flags():
        assert "Archive (read-only)" in dict(agents_bindings(km))
        footer.update_leader_bindings(current_tab="agents")
        bindings, _mode = footer._last_layout_inputs or ([], None)
        assert "toggle Archive" in " ".join(label for _, label in bindings)


def test_toggle_archive_available_from_palette_without_flag() -> None:
    from sase.ace.tui.commands import CommandContext, build_command_catalog
    from sase.ace.tui.commands.availability import is_command_available
    from sase.ace.tui.keymaps import load_keymap_registry

    catalog = {
        spec.id: spec for spec in build_command_catalog(load_keymap_registry({}))
    }
    context = CommandContext(tab="agents")
    with override_flags():
        assert is_command_available(catalog["leader.toggle_agents_archive"], context)
        assert is_command_available(catalog["agents.open_archive"], context)


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
