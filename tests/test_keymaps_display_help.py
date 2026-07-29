"""Tests for ace TUI key display and help modal bindings."""

from sase.ace.tui.keymaps import (
    footer_key_display,
    key_display_name,
    load_keymap_registry,
)
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
                "app": {"edit_query": "f5"},
                "modes": {
                    "leader_mode": {
                        "prefix": "g",
                        "keys": {"edit_query": "f", "show_help": "h"},
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
        assert ("gh", "Show this help") in pairs

    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    assert ("gf", "Filter agents by query") in agent_pairs
    assert ("gh", "Show this help") in agent_pairs


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


def test_admin_center_help_summary_includes_both_statistics_range_directions() -> None:
    reg = load_keymap_registry({})

    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        labels = {label for _section, bindings in sections for _key, label in bindings}
        assert "Admin Center: 1-7 jumps; Statistics [/] t/T/c/g/p/P/r/?" in labels


def test_leader_prefix_override_updates_repeat_last_help_display() -> None:
    """Leader help displays the configured prefix for repeat_last."""
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


def test_agents_help_uses_f_for_fork_not_r_for_resume() -> None:
    reg = load_keymap_registry({})
    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }

    assert ("f", "Fork chat as agent") in agent_pairs
    assert ("r", "Resume chat as agent") not in agent_pairs
    assert ("r", "Retry: edit prompt & relaunch") in agent_pairs
    assert ("e", "Edit chat(s) in editor") in agent_pairs
    assert ("e", "Edit chat in editor") not in agent_pairs


def test_agents_help_describes_zoom_isolation_and_capital_h_collapsing() -> None:
    reg = load_keymap_registry({})
    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }

    assert ("l", "Expand fold / enter panel (❯)") in agent_pairs
    assert ("h", "Up: workflow/family/clan/tribe") in agent_pairs
    assert ("h", "Collapse selected panel") in agent_pairs
    assert ("H", "Fully collapse lanes in scope") in agent_pairs
    assert ("H", "Then selected clan / group clans") in agent_pairs
    assert ("H", "Panel: clans / groups / panel") in agent_pairs
    assert ("H", "Compact expanded Tools detail") in agent_pairs
    assert (
        "Z",
        "Zoom detail / only panel ⇄ restore panels",
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
    assert ("x", "Clean row/panel/group/clan/marks") in agent_pairs
    assert ("S", "Bulk status change (marked PRs)") in cls_pairs


def test_agents_help_advertises_clan_cleanup_chooser() -> None:
    reg = load_keymap_registry({})
    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }

    assert ("X", "Open cleanup panel (C: clan)") in agent_pairs


def test_help_modal_lists_prompt_pane_focus_and_reorder() -> None:
    """The Prompt Input section documents prompt-local g-prefix pane actions."""
    reg = load_keymap_registry({})
    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert ("K", "Preview xprompt/skill/file/word") in pairs
        assert ("Ctrl+]", "Jump to xprompt/skill/file") in pairs
        assert ("gf / Ctrl+G f", "Format current prompt") in pairs
        assert ("gj / gk", "Focus prompt panes (NORMAL)") in pairs
        assert ("gJ / gK", "Move prompt pane (NORMAL)") in pairs
        assert ("g-", "Add prompt pane") in pairs


def test_help_modal_lists_artifact_reference_completion() -> None:
    reg = load_keymap_registry({})
    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert ("@kind:payload", "Complete artifact references") in pairs


def test_help_modal_lists_frontmatter_panel_toggle() -> None:
    """The Prompt Input section advertises the g-prefix properties toggle."""
    reg = load_keymap_registry({})
    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert ("g=", "Frontmatter panel") in pairs
        assert ("q/Esc (panel)", "Return to originating pane") in pairs
        assert ("gj/gk (panel)", "Top / bottom prompt pane") in pairs
        assert ("Ctrl+S", "Stash pane (panel if empty)") in pairs
        assert ("gs / Ctrl+G s", "Stash all panes") in pairs
        assert (
            "gx / Ctrl+G x / Ctrl+G Ctrl+X",
            "Open xprompt/snippet save panel",
        ) in pairs
        assert ("gX / Ctrl+G X", "Save pane as local xprompt") in pairs
        assert ("Ctrl+G p / @", "Stashed prompts panel") in pairs


def test_help_modal_lists_global_restore_prompt_stash() -> None:
    """Every main tab advertises ``@`` as the global prompt-stash restore key."""
    reg = load_keymap_registry({})
    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert ("@", "Restore stashed prompt") in pairs


def test_help_modal_lists_configured_leader_prompt_stash_panel() -> None:
    """All main tabs resolve the stash-panel sequence from the registry."""
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "leader_mode": {
                        "prefix": "semicolon",
                        "keys": {"open_prompt_stash": "P"},
                    }
                }
            }
        }
    )
    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert (";P", "Open stashed prompts panel") in pairs
        assert ("@", "Restore stashed prompt") in pairs


def test_help_modal_labels_lowercase_a_as_agent_artifacts() -> None:
    """Guard ``a`` as the Agents-tab artifact binding and ``A`` as accept."""
    reg = load_keymap_registry({})
    cls_sections = cls_bindings(reg)
    agents_sections = agents_bindings(reg)
    axe_sections = axe_bindings(reg)

    cls_pairs = {
        (key, label) for _section, bindings in cls_sections for key, label in bindings
    }
    assert (",A", "Agent run log") in cls_pairs

    agent_pairs = {
        (key, label)
        for _section, bindings in agents_sections
        for key, label in bindings
    }
    assert ("a", "Artifact files (or marked set)") in agent_pairs
    assert ("A", "Open auto-approve menu / answer HITL") in agent_pairs
    assert (",j", "Jump to next unread done agent") in agent_pairs
    assert ("U", "Toggle unread marker") in agent_pairs
    for sections in (cls_sections, axe_sections):
        action_labels = {
            label
            for _section, bindings in sections
            for key, label in bindings
            if key == "V"
        }
        assert "Agent run log" in action_labels


def test_agents_help_documents_inline_metadata_search() -> None:
    reg = load_keymap_registry({})
    sections = dict(agents_bindings(reg))

    assert sections["Metadata Search"] == [
        ("/ / ?", "Search metadata forward / backward"),
        ("n / N", "Next / previous match"),
        ("Enter / Esc / Ctrl+C", "Accept / cancel search query"),
        ("Esc / q", "Close committed search"),
        ("y / Y", "Yank selection/match / whole line"),
    ]


def test_key_display_special_keys() -> None:
    """Special Textual key names are mapped to display characters."""
    assert key_display_name("full_stop") == "."
    assert key_display_name("exclamation_mark") == "!"
    assert key_display_name("percent_sign") == "%"
    assert key_display_name("comma") == ","
    assert key_display_name("right_square_bracket") == "]"
    assert key_display_name("left_square_bracket") == "["
    assert key_display_name("question_mark") == "?"
    assert key_display_name("slash") == "/"
    assert key_display_name("minus") == "-"
    assert key_display_name("equals_sign") == "="
    assert key_display_name("plus") == "+"


def test_key_display_plus_friendly_spellings() -> None:
    """Raw ``+`` and the Unicode name render as ``+`` after canonicalization."""
    assert key_display_name("+") == "+"
    assert key_display_name("plus_sign") == "+"
    assert footer_key_display("plus") == "+"


def test_key_display_ctrl_keys() -> None:
    """Ctrl key combos are formatted as Ctrl+X."""
    assert key_display_name("ctrl+d") == "Ctrl+D"
    assert key_display_name("ctrl+u") == "Ctrl+U"
    assert key_display_name("ctrl+f") == "Ctrl+F"
    assert key_display_name("ctrl+@") == "Ctrl+Space"
    assert key_display_name("ctrl+space") == "Ctrl+Space"


def test_key_display_nested_modifiers() -> None:
    """Nested modifiers use title-cased names across display surfaces."""
    assert key_display_name("ctrl+shift+o") == "Ctrl+Shift+O"
    assert key_display_name("ctrl+shift+o,ctrl+k") == "Ctrl+Shift+O / Ctrl+K"
    assert footer_key_display("ctrl+shift+o") == "Ctrl+Shift+O"


def test_key_display_passthrough() -> None:
    """Single character keys pass through unchanged."""
    assert key_display_name("j") == "j"
    assert key_display_name("k") == "k"
    assert key_display_name("q") == "q"
    assert key_display_name("G") == "G"


def test_key_display_compound_alternatives() -> None:
    """Compound app bindings render as alternatives, not a key sequence."""
    assert key_display_name("colon,semicolon") == ": / ;"


def test_footer_key_display_compound_alternatives() -> None:
    """Compound app bindings keep footer formatting per alternative."""
    assert footer_key_display("colon,space") == ": / <space>"
    assert footer_key_display("ctrl+@") == "Ctrl+Space"


def test_help_modal_displays_command_palette_alternatives() -> None:
    """The help modal uses the same readable display for compound app bindings."""
    reg = load_keymap_registry({})
    entries = [
        entry
        for _section_name, section_entries in cls_bindings(reg)
        for entry in section_entries
    ]
    assert (": / ;", "Open command palette") in entries


def test_help_modal_displays_ctrl_space_agent_shortcuts() -> None:
    """Help exposes Ctrl+Space for repeat-last, not the old Space wording."""
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

    for pairs in (cls_pairs, agent_pairs, axe_pairs):
        assert ("Ctrl+Space", "Repeat last +/Ctrl+Space selection") in pairs
        assert not any("@/Space" in label for _key, label in pairs)

    assert (", Space", "Run agent from current PR") in cls_pairs
    assert (", Space", "Run agent from selected agent") in agent_pairs


def test_help_modal_displays_bare_space_agent_home_app_key() -> None:
    """Help exposes bare Space as the primary home-agent shortcut."""
    reg = load_keymap_registry({})
    sections_by_tab = (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg))

    for sections in sections_by_tab:
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert ("Space", "Run agent (home)") in pairs


def test_help_modal_displays_h_agent_home_leader_key() -> None:
    """Help renders leader h as the secondary home-agent shortcut."""
    reg = load_keymap_registry({})
    sections_by_tab = (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg))

    for sections in sections_by_tab:
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert (",h", "Run agent (home)") in pairs
        assert (", Space", "Run agent (home)") not in pairs
        assert (",Space", "Run agent (home)") not in pairs
