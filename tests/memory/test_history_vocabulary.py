"""Tests for the shared memory-history visual vocabulary."""

from __future__ import annotations

from sase.memory.history import vocabulary


def test_every_documented_class_has_a_glyph_and_label() -> None:
    expected = (
        "created",
        "authored",
        "promoted",
        "demoted",
        "frontmatter",
        "rendered",
        "regenerated",
        "config",
        "regen_only",
        "reflow",
        "whitespace",
        "moved",
        "deleted",
        "uncommitted",
        "staged",
    )
    for class_name in expected:
        assert vocabulary.glyph_for(class_name) not in ("", "?")
        assert vocabulary.label_for(class_name) != ""


def test_glyphs_match_the_design_table() -> None:
    assert vocabulary.glyph_for("created") == "✚"
    assert vocabulary.glyph_for("authored") == "◆"
    assert vocabulary.glyph_for("promoted") == "⇧"
    assert vocabulary.glyph_for("demoted") == "⇩"
    assert vocabulary.glyph_for("frontmatter") == "▣"
    assert vocabulary.glyph_for("rendered") == "⟳"
    assert vocabulary.glyph_for("regenerated") == "⟳"
    assert vocabulary.glyph_for("config") == "⚙"
    assert vocabulary.glyph_for("regen_only") == "⚙"
    assert vocabulary.glyph_for("reflow") == "≈"
    assert vocabulary.glyph_for("whitespace") == "≈"
    assert vocabulary.glyph_for("moved") == "↦"
    assert vocabulary.glyph_for("deleted") == "✖"
    assert vocabulary.glyph_for("uncommitted") == "◌"
    assert vocabulary.glyph_for("staged") == "◌"


def test_hidden_classes_mirror_the_core_bit() -> None:
    assert vocabulary.is_hidden_by_default("moved")
    assert vocabulary.is_hidden_by_default("reflow")
    assert vocabulary.is_hidden_by_default("whitespace")
    assert not vocabulary.is_hidden_by_default("authored")
    assert not vocabulary.is_hidden_by_default("promoted")
    assert not vocabulary.is_hidden_by_default("deleted")


def test_past_accent_is_distinct_from_uncommitted_amber() -> None:
    assert vocabulary.STYLE_ROLES["past"] != vocabulary.STYLE_ROLES["uncommitted"]


def test_unknown_classes_fall_back() -> None:
    assert vocabulary.glyph_for("nope") == "?"
    assert vocabulary.label_for("nope") == "nope"
