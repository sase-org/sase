"""Tests for sase's TUI help-modal side-panel sections.

Covers Prompt Input, Memory, Snippets, and Frontmatter panel sections, the
retired Glossary Panel, Copy Mode palette sections, and the global
prompt-stash restore/labels shared across all three main tabs.
"""

from sase.ace.tui.keymaps import load_keymap_registry, memory_help_bindings
from sase.ace.tui.modals.help_modal.bindings import (
    agents_bindings,
    axe_bindings,
    cls_bindings,
)


def test_help_modal_lists_prompt_pane_focus_and_reorder() -> None:
    """The Prompt Input section documents prompt-local g-prefix pane actions."""
    reg = load_keymap_registry({})
    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert ("K", "Preview xprompt/skill/file/word") in pairs
        assert ("Ctrl+]", "Jump to xprompt/skill/file/repo") in pairs
        assert ("gf / Ctrl+G f", "Format current prompt") in pairs
        assert ("gj / gk", "Focus prompt panes (NORMAL)") in pairs
        assert ("gJ / gK", "Move prompt pane (NORMAL)") in pairs
        assert ("g-", "Add prompt pane") in pairs


def test_help_modal_lists_at_reference_completion() -> None:
    reg = load_keymap_registry({})
    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert ("@", "Artifact kinds; Ctrl+T files") in pairs


def test_help_modal_no_longer_lists_glossary_panel_section() -> None:
    """The retired Glossary Panel keybinding section no longer builds.

    ``PROMPT_INPUT_SECTION`` still advertises the ``gG`` pane-opening
    shortcut by name (that belongs to the separate pane-deletion effort),
    but the panel's own keybinding section -- built from the now-removed
    ``KeymapRegistry.glossary`` -- must be gone.
    """
    reg = load_keymap_registry({})
    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        names = {name for name, _bindings in sections}
        assert "Glossary Panel" not in names


def test_help_modal_lists_memory_panel() -> None:
    """The Memory Panel section advertises gm / Ctrl+G m and panel keys."""
    reg = load_keymap_registry({})
    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        names = {name for name, _bindings in sections}
        assert ("gm / Ctrl+G m", "Memory panel") in pairs
        assert ("gm / Ctrl+G m", "Open from prompt") in pairs
        assert "Memory Panel" in names
        assert ("j / k", "Move through notes") in pairs
        assert (">", "Match note bodies") in pairs
        assert ("Ctrl+P", "Pick a scope") in pairs
        assert ("I", "Publish unpublished") in pairs
        assert (".1-9", "Follow numbered chip") in pairs
        assert ("Esc", "Close and restore prompt") in pairs
        for _name, bindings in sections:
            if _name != "Memory Panel":
                continue
            for key, description in bindings:
                assert len(key) <= 16, key
                assert len(description) <= 32, description


def test_panel_scoped_help_lists_prefixed_chip_shortcut() -> None:
    reg = load_keymap_registry({})
    assert (".1-9", "Follow numbered chip") in memory_help_bindings(reg.memory)


def test_help_modal_lists_snippets_panel() -> None:
    """The Snippets Panel section advertises gT / Ctrl+G T and panel keys."""
    reg = load_keymap_registry({})
    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        names = {name for name, _bindings in sections}
        assert ("gT / Ctrl+G T", "Snippets panel") in pairs
        assert ("gT / Ctrl+G T", "Open from prompt") in pairs
        assert "Snippets Panel" in names
        assert ("j / k", "Move through snippets") in pairs
        assert ("1-9", "Follow numbered chip") in pairs
        assert ("Esc", "Close and restore prompt") in pairs
        for _name, bindings in sections:
            if _name != "Snippets Panel":
                continue
            for key, description in bindings:
                assert len(key) <= 16, key
                assert len(description) <= 32, description


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
        assert ("gx / Ctrl+G x / Ctrl+G Ctrl+X", "Open mini-xprompt pane") in pairs
        assert (
            "gX / Ctrl+G X",
            "Open xprompt/snippet save panel",
        ) in pairs
        assert ("gL / Ctrl+G L", "Save pane as local xprompt") in pairs
        assert ("Ctrl+G p / @", "Stashed prompts panel") in pairs


def test_help_modal_lists_global_restore_prompt_stash() -> None:
    """Every main tab advertises ``@`` as the global prompt-stash restore key."""
    reg = load_keymap_registry({})
    for sections in (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg)):
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert ("@", "Restore stashed prompt") in pairs


def test_help_copy_sections_advertise_copy_as_palette() -> None:
    reg = load_keymap_registry({})
    expected_section_counts = (
        (cls_bindings(reg), 5),
        (agents_bindings(reg), 1),
        (axe_bindings(reg), 1),
    )

    for sections, expected_count in expected_section_counts:
        copy_sections = [
            bindings for title, bindings in sections if title.startswith("Copy Mode")
        ]
        assert len(copy_sections) == expected_count
        assert all(("%", "Open Copy as… palette") in rows for rows in copy_sections)

    other_rows = next(
        bindings
        for title, bindings in cls_bindings(reg)
        if title.startswith("Copy Mode · Other")
    )
    assert ("%L", "Copy Markdown link") in other_rows
    assert ("%l", "Copy artifact-file label") in other_rows
    assert ("%j", "Copy metadata JSON") in other_rows


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
    assert ("A", "Auto-approve / answer local or remote attention") in agent_pairs
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
