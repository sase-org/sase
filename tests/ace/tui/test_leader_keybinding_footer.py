"""Tests for leader-mode keybinding footer display."""

from __future__ import annotations

from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.widgets import KeybindingFooter

from tests.ace.tui._leader_keymap_helpers import (
    _capture_bindings,
    _last_keys,
    _last_labels,
)


def test_footer_surfaces_agent_run_log_only_on_cls_tab() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    footer.update_leader_bindings(current_tab="changespecs")
    assert "A" in _last_keys(captured)
    assert "agent run log" in _last_labels(captured)

    for tab in ("agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert "agent run log" not in _last_labels(captured)


def test_footer_surfaces_panel_grouping_only_on_agents_tab() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    footer.update_leader_bindings(current_tab="agents")
    assert "g" in _last_keys(captured)
    assert "group panels" in _last_labels(captured)

    footer.update_leader_bindings(current_tab="changespecs")
    assert "group panels" not in _last_labels(captured)


def test_footer_surfaces_repeat_last_on_all_tabs() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("changespecs", "agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert "," in _last_keys(captured)
        assert "repeat" in _last_labels(captured)


def test_footer_surfaces_configured_prompt_stash_key_on_all_tabs() -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(
        load_keymap_registry(
            {
                "keymaps": {
                    "modes": {"leader_mode": {"keys": {"open_prompt_stash": "P"}}}
                }
            }
        )
    )
    captured = _capture_bindings(footer)

    for tab in ("changespecs", "agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert ("P", "prompt stash") in captured[-1][0]


def test_footer_omits_tab_guide_after_help_panel_merge() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("changespecs", "agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert "tab guide" not in _last_labels(captured)


def test_footer_surfaces_update_sase_on_all_tabs() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("changespecs", "agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert "U" in _last_keys(captured)
        assert "update sase" in _last_labels(captured)


def test_footer_surfaces_agent_home_as_h_on_all_tabs() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("changespecs", "agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert ("h", "agent (home)") in captured[-1][0]
        assert ("<space>", "agent (home)") not in captured[-1][0]


def test_footer_omits_project_management_after_cutover() -> None:
    """The ``,p`` projects entry was retired when the panel moved to the
    Admin Center's Projects tab, so the leader footer no longer surfaces it."""
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("changespecs", "agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert "projects" not in _last_labels(captured)


def test_footer_omits_log_panel_after_cutover() -> None:
    """The ``,L`` logs entry was retired when the panel moved to the
    Admin Center's Logs tab, so the leader footer no longer surfaces it."""
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("changespecs", "agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert "log panel" not in _last_labels(captured)


def test_footer_omits_task_queue_after_cutover() -> None:
    """The ``,t`` tasks entry was retired when the panel moved to the
    Admin Center's Tasks tab, so the leader footer no longer surfaces it."""
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("changespecs", "agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert "task queue" not in _last_labels(captured)


def test_footer_surfaces_space_run_agent_on_cl_and_agents_tabs() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("changespecs", "agents"):
        footer.update_leader_bindings(current_tab=tab)
        assert "<space>" in _last_keys(captured)
        assert "run agent (PR)" in _last_labels(captured)

    footer.update_leader_bindings(current_tab="axe")
    assert "run agent (PR)" not in _last_labels(captured)


def test_footer_surfaces_configured_repeat_last_key() -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(
        load_keymap_registry(
            {"keymaps": {"modes": {"leader_mode": {"keys": {"repeat_last": "R"}}}}}
        )
    )
    captured = _capture_bindings(footer)

    footer.update_leader_bindings(current_tab="agents")

    assert "R" in _last_keys(captured)
    assert "repeat" in _last_labels(captured)


def test_footer_surfaces_unread_done_jump_only_when_available() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    footer.update_leader_bindings(current_tab="agents", has_unread_completed_agent=True)
    assert "j" in _last_keys(captured)
    assert "next unread done" in _last_labels(captured)
    assert "u" in _last_keys(captured)
    assert "mark all read" in _last_labels(captured)

    footer.update_leader_bindings(
        current_tab="agents", has_unread_completed_agent=False
    )
    assert "next unread done" not in _last_labels(captured)
    assert "mark all read" not in _last_labels(captured)


def test_footer_surfaces_stopped_jump_only_when_available() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    footer.update_leader_bindings(current_tab="agents", has_stopped_agent=True)
    assert "J" in _last_keys(captured)
    assert "next stopped" in _last_labels(captured)

    footer.update_leader_bindings(current_tab="agents", has_stopped_agent=False)
    assert "next stopped" not in _last_labels(captured)


def test_footer_surfaces_revert_only_when_revertable() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    footer.update_leader_bindings(current_tab="agents", has_revertable_agent=True)
    assert "r" in _last_keys(captured)
    assert "revert agent" in _last_labels(captured)

    footer.update_leader_bindings(current_tab="agents", has_revertable_agent=False)
    assert "revert agent" not in _last_labels(captured)


def test_footer_omits_revert_on_non_agents_tabs() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("changespecs", "axe"):
        footer.update_leader_bindings(current_tab=tab, has_revertable_agent=True)
        assert "revert agent" not in _last_labels(captured)


def test_footer_advertises_revert_marked_when_marks_exist() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    footer.update_leader_bindings(current_tab="agents", marked_agent_count=3)
    assert "r" in _last_keys(captured)
    assert "revert marked (3)" in _last_labels(captured)
    assert "revert agent" not in _last_labels(captured)


def test_footer_marked_revert_overrides_single_revert_label() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    # Marks take priority over the single-agent "revert agent" label.
    footer.update_leader_bindings(
        current_tab="agents", has_revertable_agent=True, marked_agent_count=2
    )
    assert "revert marked (2)" in _last_labels(captured)
    assert "revert agent" not in _last_labels(captured)
