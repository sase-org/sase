"""Tests for sase's TUI key display formatting.

Covers ``key_display_name`` / ``footer_key_display`` formatting rules and
how the help modal surfaces those display strings for compound app
bindings and agent shortcuts.
"""

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


def test_key_display_special_keys() -> None:
    """Special Textual key names are mapped to display characters."""
    assert key_display_name("full_stop") == "."
    assert key_display_name("exclamation_mark") == "!"
    assert key_display_name("percent_sign") == "%"
    assert key_display_name("comma") == ","
    assert key_display_name("right_square_bracket") == "]"
    assert key_display_name("left_square_bracket") == "["
    assert key_display_name("right_parenthesis") == ")"
    assert key_display_name("left_parenthesis") == "("
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


def test_help_modal_displays_space_repeat_agent_shortcuts() -> None:
    """Help exposes Space for repeat-last with no home-agent app row."""
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
        assert ("Space", "Repeat last launched VCS xprompt") in pairs
        assert ("Space", "Run agent (home)") not in pairs
        assert not any("@/Space" in label for _key, label in pairs)

    assert (", Space", "Run agent from current Patch") in cls_pairs
    assert (", Space", "Run agent from selected agent") in agent_pairs


def test_help_modal_displays_bare_space_repeat_agent_app_key() -> None:
    """Help exposes bare Space as the primary repeat-last shortcut."""
    reg = load_keymap_registry({})
    sections_by_tab = (cls_bindings(reg), agents_bindings(reg), axe_bindings(reg))

    for sections in sections_by_tab:
        pairs = {
            (key, label) for _section, bindings in sections for key, label in bindings
        }
        assert ("Space", "Repeat last launched VCS xprompt") in pairs


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
