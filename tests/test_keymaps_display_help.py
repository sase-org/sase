"""Tests for ace TUI help-modal display of leader-mode and config overrides.

Covers leader-mode prefix/key overrides, contextual query/help rebindings,
and the Admin Center / Projects / PRs sections shared across all three
main-tab help builders (Patches, Agents, Axe).
"""

from sase.ace.tui.keymaps import key_display_name, load_keymap_registry
from sase.ace.tui.modals.help_modal.bindings import (
    agents_bindings,
    axe_bindings,
    cls_bindings,
)


def test_leader_repeat_last_override_updates_help_display() -> None:
    """User overrides for repeat_last flow through help-display surfaces."""
    reg = load_keymap_registry(
        {"keymaps": {"modes": {"leader_mode": {"keys": {"repeat_last": "R"}}}}}
    )
    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert (",R", "Repeat last leader command") in pairs


def test_contextual_query_and_help_overrides_update_help_displays() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "app": {"edit_query": "f5", "show_help": "f6"},
                "modes": {
                    "leader_mode": {
                        "prefix": "g",
                        "keys": {"search_forward": "f", "show_help": "h"},
                    }
                },
            }
        }
    )

    for sections in (cls_bindings(reg), axe_bindings(reg)):
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert ("f5", "Edit search query") in pairs
        assert not any(key == "gf" and "query" in label.lower() for key, label in pairs)
        assert ("f6", "Show this help") in pairs
        assert ("gh", "Show this help") not in pairs

    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    filters_key = key_display_name(reg.app.agents_filters)
    assert (f"f5 / {filters_key}", "Filter agents by query") in agent_pairs
    assert ("gf", "Start metadata search forward") in agent_pairs
    assert ("f6", "Show this help") in agent_pairs
    assert ("gh", "Show this help") not in agent_pairs


def test_agents_help_uses_configured_direct_visible_fold_selector_key() -> None:
    reg = load_keymap_registry({"keymaps": {"app": {"expand_all_folds": "P"}}})
    pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }

    assert ("P", "Toggle tribe fold by hint key") in pairs
    assert not any(
        key.startswith(",") and "tribe fold" in label.lower() for key, label in pairs
    )


def test_agents_help_lists_panel_fold_sweep_binding() -> None:
    reg = load_keymap_registry({})
    pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }

    assert ("-", "Collapse panel folds ⇄ restore ▿") in pairs


def test_agents_help_uses_configured_panel_fold_sweep_key() -> None:
    reg = load_keymap_registry({"keymaps": {"app": {"collapse_panel_folds": "f4"}}})
    pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }

    assert ("f4", "Collapse panel folds ⇄ restore ▿") in pairs


def test_help_panel_tab_switch_display_is_present() -> None:
    reg = load_keymap_registry({})
    cls_pairs = {
        (key, label)
        for _section, bindings in cls_bindings(reg)
        for key, label in bindings
    }
    assert ("[ / ]", "In help: switch Keymaps / Guide") in cls_pairs

    for sections in (agents_bindings(reg), axe_bindings(reg)):
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert ("[ / ]", "Switch Keymaps / Guide") in pairs


def test_axe_help_lists_description_toggle() -> None:
    pairs = {
        (key, label)
        for _section, bindings in axe_bindings(load_keymap_registry({}))
        for key, label in bindings
    }

    assert ("d", "Expand / collapse description") in pairs


def test_admin_center_help_summary_fits_and_documents_the_opener_toggle() -> None:
    reg = load_keymap_registry({})

    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        labels = {label for _section, bindings in sections for _key, label in bindings}
        assert "Admin Center: 1-7 jump, # back" in labels


def test_help_lists_admin_center_projects_init_keys() -> None:
    """Every main-tab help surface lists the Projects ``i`` / ``I`` init keys."""
    reg = load_keymap_registry({})

    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        titles = {title for title, _bindings in sections}
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert "Admin Center Projects" in titles
        assert ("i", "Initialize marked or highlighted") in pairs
        assert ("I", "Initialize every enabled project") in pairs


def test_help_projects_init_keys_follow_configured_bindings() -> None:
    """Rebound Projects init keys appear in help instead of the defaults."""
    reg = load_keymap_registry(
        {
            "keymaps": {
                "projects": {
                    "initialize_project": "f7",
                    "initialize_all_projects": "f8",
                }
            }
        }
    )

    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert ("f7", "Initialize marked or highlighted") in pairs
        assert ("f8", "Initialize every enabled project") in pairs
        assert ("i", "Initialize marked or highlighted") not in pairs
        assert ("I", "Initialize every enabled project") not in pairs


def test_leader_prefix_override_updates_repeat_last_help_display() -> None:
    """Leader-mode help displays the configured prefix for repeat_last."""
    reg = load_keymap_registry(
        {"keymaps": {"modes": {"leader_mode": {"prefix": "space"}}}}
    )
    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert ("Space,", "Repeat last leader command") in pairs


def test_prs_help_pins_review_mentors_to_uppercase_c() -> None:
    """PRs help advertises Mentor Review on ``,C`` and keeps it PRs-only."""
    reg = load_keymap_registry({})
    cls_pairs = {
        (key, label)
        for _section, bindings in cls_bindings(reg)
        for key, label in bindings
    }
    assert (",C", "Review mentor comments") in cls_pairs

    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    assert not any(label == "Review mentor comments" for _key, label in agent_pairs)


def test_prs_help_describes_patch_filter_bar_binding() -> None:
    reg = load_keymap_registry({})
    cls_pairs = {
        (key, label)
        for _section, bindings in cls_bindings(reg)
        for key, label in bindings
    }

    assert (
        f"{key_display_name(reg.app.patches_filters)} / "
        f"{key_display_name(reg.app.edit_query)}",
        "Focus persistent Patch filter",
    ) in cls_pairs


def test_agents_help_uses_edit_hooks_for_fork_not_r_for_resume() -> None:
    reg = load_keymap_registry({})
    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }

    assert (
        key_display_name(reg.app.edit_hooks),
        "Fork local or remote agent",
    ) in agent_pairs
    assert ("r", "Resume chat as agent") not in agent_pairs
    assert ("R", "Retry local or remote agent") in agent_pairs
    assert ("r", "Open Refresh panel") in agent_pairs
    assert ("e", "Edit chat(s) / open remote content") in agent_pairs
    assert ("e", "Edit chat in editor") not in agent_pairs
