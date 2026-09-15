"""Tests for sase's TUI Agents-tab help-modal bindings.

Covers Agents-tab-specific sections: zoom/isolation, neighbor navigation,
tmux workspace chooser, save/dismiss/cleanup actions, wait badges, inline
metadata search, and hint-collapse fold bindings.
"""

from sase.ace.tui.keymaps import (
    key_display_name,
    leader_key_display,
    load_keymap_registry,
)
from sase.ace.tui.modals.help_modal.bindings import (
    agents_bindings,
    axe_bindings,
    cls_bindings,
)


def test_agents_help_describes_zoom_and_isolation_and_capital_h_collapsing() -> None:
    reg = load_keymap_registry({})
    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }

    assert ("l", "Expand fold / enter panel (❯)") in agent_pairs
    assert ("h", "Up: workflow/family/clan/tribe") in agent_pairs
    assert ("h", "Collapse selected panel") in agent_pairs
    assert ("H", "Panel: collapse fold by hint key") in agent_pairs
    assert ("H", "Collapse selected workflow/family one level") in agent_pairs
    assert ("H", "Then remaining sase agents in scope") in agent_pairs
    assert ("H", "Then selected clan / group clans") in agent_pairs
    assert ("H", "Compact expanded Tools detail") in agent_pairs
    assert ("Z", "Zoom agent/tribe detail") in agent_pairs
    assert (
        "=",
        "Only panel ⇄ restore panels",
    ) in agent_pairs


def test_agents_help_lists_neighbor_navigation() -> None:
    reg = load_keymap_registry({})
    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    cls_pairs = {
        (key, label)
        for _section, bindings in cls_bindings(reg)
        for key, label in bindings
    }

    assert ("~", "Jump ancestor/neighbor/desc") in agent_pairs
    assert ("< / > / ~", "Navigate to ancestor / child / sibling") in cls_pairs


def test_all_tab_help_guides_show_forward_jump_and_agents_metadata_sections() -> None:
    reg = load_keymap_registry({})
    cls_pairs = {
        (key, label)
        for _section, bindings in cls_bindings(reg)
        for key, label in bindings
    }
    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    axe_pairs = {
        (key, label)
        for _section, bindings in axe_bindings(reg)
        for key, label in bindings
    }

    jump_pair = ("Ctrl+O / Ctrl+Shift+O", "Jump stack back / forward")
    assert jump_pair in cls_pairs
    assert jump_pair in agent_pairs
    assert jump_pair in axe_pairs
    assert ("Ctrl+J / Ctrl+K", "Cycle metadata through top") in agent_pairs
    assert not any(label == "Cycle metadata through top" for _key, label in cls_pairs)
    assert not any(label == "Cycle metadata through top" for _key, label in axe_pairs)


def test_agents_help_describes_tmux_workspace_chooser() -> None:
    reg = load_keymap_registry({})
    labels = {
        label for _section, bindings in agents_bindings(reg) for _key, label in bindings
    }

    assert "Tmux workspace chooser" in labels
    assert "Tmux in agent workspace" not in labels
    assert "Tmux in primary workspace" in labels


def test_agents_help_lists_save_dismiss_marked_agents() -> None:
    reg = load_keymap_registry({})
    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    cls_pairs = {
        (key, label)
        for _section, bindings in cls_bindings(reg)
        for key, label in bindings
    }

    assert ("s", "Save/dismiss marked agents") in agent_pairs
    assert ("x", "Stop/clean row/panel/group/clan/marks") in agent_pairs
    assert ("S", "Bulk status change (marked Patches)") in cls_pairs


def test_agents_help_advertises_cleanup_panel() -> None:
    reg = load_keymap_registry({})
    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }

    assert ("X", "Open cleanup panel") in agent_pairs


def test_agents_help_documents_two_domain_wait_badges() -> None:
    sections = dict(agents_bindings(load_keymap_registry({})))
    badges = dict(sections["Waiting Badges"])

    assert badges["▶2 ✓1 ?1"] == "Agent wait counts"
    assert badges["○2 ◐1"] == "Bead wait counts"
    assert badges["▶1 ◐2"] == "Bead follows matching agent"
    assert badges["✓1 ●1"] == "Closed bead follows done agent"
    assert badges["◇1 ◈1"] == "Unmatched beads trail"
    assert badges["?1 ?2"] == "Unknown agent + bead"
    assert badges["?N"] == "Unknown agent or bead"
    assert badges["[beads] id ◐"] == "Bead wait target status"
    assert "beads: id ✓" not in badges


def test_agents_help_documents_inline_metadata_search() -> None:
    reg = load_keymap_registry({})
    sections = dict(agents_bindings(reg))
    filters_key = key_display_name(reg.app.agents_filters)

    assert sections["Agent Query"] == [
        (
            f"{key_display_name(reg.app.edit_query)} / {filters_key}",
            "Filter agents by query",
        ),
    ]
    assert sections["Metadata Search"] == [
        (leader_key_display(reg, "search_forward"), "Start metadata search forward"),
        ("Ctrl+R", "Reverse active search order"),
        ("n / N", "Next / previous match"),
        ("Enter / Esc / Ctrl+C", "Accept / cancel search query"),
        ("Esc / q", "Close committed search"),
        ("y / Y", "Yank selection/match / whole line"),
    ]


def test_help_modal_lists_collapse_fold_by_hint_with_configured_prefix() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "leader_mode": {
                        "prefix": "semicolon",
                        "keys": {"collapse_fold_by_hint": "H"},
                    }
                }
            }
        }
    )
    pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    assert (";H", "Collapse fold by hint") in pairs
    assert (";H", "Row: tribe hints; panel: all") in pairs
