"""Tests for ace TUI app binding construction."""

from sase.ace.tui.keymaps import build_app_bindings
from tests._keymaps_helpers import default_app_keymaps


def test_build_app_bindings_count() -> None:
    """build_app_bindings produces 84 configurable + 10 digit = 94 bindings."""
    bindings = build_app_bindings(default_app_keymaps())
    assert len(bindings) == 94


def test_file_trim_actions_are_not_configurable_bindings() -> None:
    actions = {binding.action for binding in build_app_bindings(default_app_keymaps())}

    assert "reset_file_trim" not in actions
    assert "show_all_file_lines" not in actions


def test_build_app_bindings_priority() -> None:
    """next_tab and prev_tab have priority=True, others don't."""
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    assert by_action["next_tab"].priority is True
    assert by_action["prev_tab"].priority is True
    assert by_action["next_changespec"].priority is False
    assert by_action["quit"].priority is False


def test_build_app_bindings_uses_config_keys() -> None:
    """Bindings reflect overridden keys from AppKeymaps."""
    km = default_app_keymaps(next_changespec="n", quit="Q")
    bindings = build_app_bindings(km)
    by_action = {b.action: b for b in bindings}
    assert by_action["next_changespec"].key == "n"
    assert by_action["quit"].key == "Q"


def test_build_app_bindings_uses_plus_custom_agent_binding() -> None:
    """The custom-agent launcher builds a ``plus`` binding, not ``at``."""
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    by_key = {b.key: b.action for b in bindings}

    assert by_action["start_custom_agent"].key == "plus"
    assert by_key.get("plus") == "start_custom_agent"
    assert not any(b.action == "start_custom_agent" and b.key == "at" for b in bindings)


def test_build_app_bindings_binds_at_to_restore_prompt_stash() -> None:
    """Bare ``@`` (Textual ``at``) is the global prompt-stash restore binding."""
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    by_key = {b.key: b.action for b in bindings}

    assert by_action["restore_prompt_stash"].key == "at"
    assert by_key.get("at") == "restore_prompt_stash"


def test_build_app_bindings_uses_ctrl_space_agent_binding() -> None:
    """Agent home uses Space while repeat-last keeps Ctrl+Space."""
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    by_key = {b.key: b.action for b in bindings}

    assert by_action["start_agent_home"].key == "space"
    assert by_action["start_agent_from_changespec"].key == "ctrl+@"
    assert by_key["space"] == "start_agent_home"
    assert not any(
        b.action == "start_agent_from_changespec" and b.key == "space" for b in bindings
    )


def test_default_lowercase_s_bindings_are_tab_scoped_and_ordered() -> None:
    """Default ``s`` is intentionally shared by PR status and Agents save."""
    bindings = build_app_bindings(default_app_keymaps())
    assert [b.action for b in bindings if b.key == "s"] == [
        "change_status",
        "save_marked_agents",
    ]


def test_capital_x_binds_agent_cleanup_panel() -> None:
    """Capital X is the single cleanup entry point."""
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    assert by_action["open_agent_cleanup_panel"].key == "X"


def test_lowercase_a_binds_agent_artifacts_and_capital_a_accepts() -> None:
    """Lowercase ``a`` opens agent artifacts; capital ``A`` accepts/auto-approves.

    Guards the swapped Agents-tab defaults: ``a`` opens artifacts and ``A``
    drives accept_proposal (PR proposal acceptance + Agents-tab auto-approve/HITL).
    """
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    assert by_action["open_agent_artifacts"].key == "a"
    assert by_action["accept_proposal"].key == "A"
    assert by_action["show_agent_run_log"].key == "V"
    assert by_action["toggle_attempt_view"].key == "D"
    assert by_action["toggle_agent_unread"].key == "U"


def test_ctrl_o_and_ctrl_k_bind_jump_stack_navigation() -> None:
    """Ctrl+O/Ctrl+K are the back/forward jump-stack bindings."""
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}

    assert by_action["jump_to_entry_fast"].key == "ctrl+o"
    assert by_action["jump_to_entry_forward"].key == "ctrl+k"
    assert "prev_changespec_history" not in by_action
    assert "next_changespec_history" not in by_action
    assert [b.action for b in bindings if b.key == "ctrl+o"] == ["jump_to_entry_fast"]
    assert [b.action for b in bindings if b.key == "ctrl+k"] == [
        "jump_to_entry_forward"
    ]


def test_build_app_bindings_preserves_compound_key() -> None:
    """Compound Textual binding strings stay on the single configured action."""
    km = default_app_keymaps(open_command_palette="colon,semicolon")
    bindings = build_app_bindings(km)
    by_action = {b.action: b for b in bindings}
    assert by_action["open_command_palette"].key == "colon,semicolon"


def test_build_app_bindings_digit_keys() -> None:
    """Digit bindings 0-9 are always appended."""
    bindings = build_app_bindings(default_app_keymaps())
    digit_actions = [b for b in bindings if b.action.startswith("load_saved_query")]
    assert len(digit_actions) == 10
    digit_keys = {b.key for b in digit_actions}
    assert digit_keys == {str(d) for d in range(10)}
