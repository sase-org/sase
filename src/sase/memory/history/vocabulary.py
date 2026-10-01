"""One shared visual vocabulary for memory history.

The CLI, band, picker, feed, and Memory panel all use the same glyphs
(epic design ``plan:202609/memory_history.md`` §4.10). They are defined
once here and mapped from the core's class enum; nothing else in the
repo may invent its own history glyphs.
"""

from __future__ import annotations

#: Glyph per core version class (``MemoryHistoryClassWire``).
CLASS_GLYPHS: dict[str, str] = {
    "created": "✚",
    "authored": "◆",
    "promoted": "⇧",
    "demoted": "⇩",
    "frontmatter": "▣",
    "rendered": "⟳",
    "regenerated": "⟳",
    "config": "⚙",
    "regen_only": "⚙",
    "reflow": "≈",
    "whitespace": "≈",
    "moved": "↦",
    "deleted": "✖",
    "uncommitted": "◌",
    "staged": "◌",
    "unclassified": "?",
}

#: Classes hidden unless ``-a/--all`` is passed. Mirrors the core's
#: ``hidden_by_default`` bit (``moved``, ``reflow``, ``whitespace``).
HIDDEN_CLASSES: frozenset[str] = frozenset(("moved", "reflow", "whitespace"))

#: Short human label per class for timeline and feed rows.
CLASS_LABELS: dict[str, str] = {
    "created": "created",
    "authored": "edited",
    "promoted": "promoted",
    "demoted": "demoted",
    "frontmatter": "frontmatter",
    "rendered": "rendered",
    "regenerated": "regenerated",
    "config": "config",
    "regen_only": "regen-only",
    "reflow": "reflow",
    "whitespace": "whitespace",
    "moved": "moved",
    "deleted": "deleted",
    "uncommitted": "uncommitted",
    "staged": "staged",
    "unclassified": "unclassified",
}

#: Rich style roles for history chrome. TTY only; piped output is plain.
#: Every role uses theme-agnostic color names so both light and dark
#: themes stay legible. The past accent stays violet, never amber:
#: amber already means uncommitted or unpublished.
STYLE_ROLES: dict[str, str] = {
    "past": "magenta",
    "insert": "green",
    "delete": "red strike",
    "gutter_add": "green",
    "gutter_change": "magenta",
    "gutter_remove": "red",
    "tombstone": "red",
    "uncommitted": "yellow",
    "dim": "dim",
}

#: Tag interleaved home changesets carry in the feed.
HOME_TAG = "⌂"


def glyph_for(class_name: str) -> str:
    """Return the vocabulary glyph for a core version class."""
    return CLASS_GLYPHS.get(class_name, "?")


def label_for(class_name: str) -> str:
    """Return the short human label for a core version class."""
    return CLASS_LABELS.get(class_name, class_name)


def is_hidden_by_default(class_name: str) -> bool:
    """Return whether a class is hidden unless ``-a/--all`` is passed."""
    return class_name in HIDDEN_CLASSES


__all__ = [
    "CLASS_GLYPHS",
    "CLASS_LABELS",
    "HIDDEN_CLASSES",
    "HOME_TAG",
    "STYLE_ROLES",
    "glyph_for",
    "is_hidden_by_default",
    "label_for",
]
