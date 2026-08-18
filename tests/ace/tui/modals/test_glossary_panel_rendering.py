"""Rendering helper tests for the Glossary panel shell."""

from __future__ import annotations

from sase.ace.tui.keymaps.app_keymaps import GlossaryPanelKeymaps
from sase.ace.tui.modals.glossary_panel_rendering import (
    build_empty_project_message,
    build_panel_footer,
    build_trail_strip,
)


def test_trail_strip_shows_full_path_when_short() -> None:
    text = build_trail_strip(
        ("Artifact Reference", "Sase Agent", "Agent Hood"), accent="#87D7FF"
    )

    assert text.plain == "TRAIL  Artifact Reference › Sase Agent › Agent Hood"


def test_trail_strip_elides_middle_when_long_and_first_is_kept() -> None:
    path = tuple(f"Term {index:02d} With A Long Name" for index in range(10))

    text = build_trail_strip(path, accent="#87D7FF", max_width=40)

    assert text.plain.startswith(f"TRAIL  {path[0]}")
    assert "…" in text.plain
    assert text.plain.endswith(f"{path[-2]} › {path[-1]}")
    for middle in path[1:-2]:
        assert middle not in text.plain


def test_trail_strip_keeps_three_entries_even_if_long() -> None:
    path = tuple(f"Term With A Fairly Long Name {index}" for index in range(3))

    text = build_trail_strip(path, accent="#87D7FF", max_width=10)

    assert "…" not in text.plain
    for entry in path:
        assert entry in text.plain


def test_empty_project_message_names_display_name() -> None:
    text = build_empty_project_message("Research", accent="#87D7FF")

    assert text.plain == (
        "No glossary in Research yet.\n\nPress a to add the first term."
    )
    assert "gh_" not in text.plain


def test_panel_footer_lists_only_conditional_keys() -> None:
    keymaps = GlossaryPanelKeymaps()

    assert (
        build_panel_footer(
            keymaps, has_entries=False, has_source_path=False, ring_size=1
        )
        == ""
    )

    footer = build_panel_footer(
        keymaps,
        has_entries=True,
        has_source_path=True,
        ring_size=2,
        has_relations=True,
        has_trail=True,
        focused_relation_term="Sase Agent",
    )
    assert "p/P project" in footer
    assert "Tab relation" in footer
    assert "Enter / l follow" in footer
    assert "→ Sase Agent" in footer
    assert "backspace / h back" in footer
    assert "d delete" in footer
    assert "y copy" in footer
    assert "o edit" in footer
    assert "Z view" in footer
    assert "a add" not in footer
    assert "filter" not in footer
    assert "help" not in footer
    assert "esc" not in footer
    assert "j/" not in footer
    assert "refresh" not in footer
