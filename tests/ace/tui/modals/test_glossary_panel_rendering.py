"""Rendering helper tests for the Glossary panel shell."""

from __future__ import annotations

from sase.ace.tui.modals.glossary_panel_rendering import build_trail_strip


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
