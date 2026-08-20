"""Tests for theme-derived glossary and repo styles."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.util.semantic_styles import semantic_highlight_styles_from_theme


def test_glossary_and_repo_roles_differ_and_follow_theme() -> None:
    dark = semantic_highlight_styles_from_theme(
        SimpleNamespace(
            primary="#AD8301",
            accent="#907AA9",
            foreground="#FFFCF0",
            background="#100F0F",
        )
    )
    light = semantic_highlight_styles_from_theme(
        SimpleNamespace(
            primary="#AD8301",
            accent="#907AA9",
            foreground="#100F0F",
            background="#FFFCF0",
        )
    )
    assert dark is not None
    assert light is not None
    assert dark.glossary.bold is True
    assert dark.glossary.underline is True
    assert dark.repo.bold is True
    assert dark.repo.underline is True
    assert dark.glossary.color != dark.repo.color
    assert dark.signature != light.signature
    assert semantic_highlight_styles_from_theme(None) is None
