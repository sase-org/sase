"""Tests for Textual-free bead-mention recognition."""

from __future__ import annotations

import pytest

from sase.bead.mentions import bead_mention_at


@pytest.mark.parametrize(
    ("text", "offset"),
    [
        ("sase-1ss", 0),
        ("sase-1ss", 4),
        ("sase-1ss", 8),
        ("see sase-1ss here", 4),
        ("see sase-1ss here", 8),
        ("see sase-1ss here", 12),
    ],
)
def test_bare_id_covers_start_middle_and_end(text: str, offset: int) -> None:
    mention = bead_mention_at(text, offset)
    assert mention is not None
    assert mention.bead_id == "sase-1ss"
    assert mention.form == "bare"
    assert mention.prefix == "sase"


def test_phase_id_is_a_bare_mention() -> None:
    text = "sase-1ss.1"
    mention = bead_mention_at(text, len(text))
    assert mention is not None
    assert mention.bead_id == "sase-1ss.1"
    assert mention.form == "bare"


@pytest.mark.parametrize(
    "text",
    [
        "sase-1ss.",
        "sase-1ss,",
        "sase-1ss)",
        "`sase-1ss`",
        "(sase-1ss)",
    ],
)
def test_trailing_punctuation_and_wrappers_are_stripped(text: str) -> None:
    start = text.index("sase-1ss")
    mention = bead_mention_at(text, start)
    assert mention is not None
    assert mention.bead_id == "sase-1ss"
    assert mention.form == "bare"


def test_multiline_offset_finds_the_id() -> None:
    text = "hello\nsase-1ss\nworld"
    offset = text.index("sase-1ss")
    mention = bead_mention_at(text, offset)
    assert mention is not None
    assert mention.bead_id == "sase-1ss"


def test_whitespace_is_not_a_mention() -> None:
    assert bead_mention_at("   ", 1) is None
    assert bead_mention_at("", 0) is None


@pytest.mark.parametrize(
    ("text", "offset"),
    [
        ("@bead:sase-1ss", 0),
        ("@bead:sase-1ss", 1),
        ("@bead:sase-1ss", 6),
        ("@bead:sase-1ss", 14),
        ("bead:sase-1ss", 0),
        ("bead:sase-1ss", 4),
        ("bead:sase-1ss", 13),
        ("see @bead:sase-1ss.1.", 4),
    ],
)
def test_ref_form_covers_sigil_and_kind(text: str, offset: int) -> None:
    mention = bead_mention_at(text, offset)
    assert mention is not None
    assert mention.form == "ref"
    assert mention.bead_id.startswith("sase-1ss")


def test_wait_directive_allows_the_id_after_colon() -> None:
    text = "%wait:sase-1ss"
    mention = bead_mention_at(text, 6)
    assert mention is not None
    assert mention.bead_id == "sase-1ss"
    assert mention.form == "bare"


@pytest.mark.parametrize(
    "text",
    [
        "src/sase-1ss/x",
        ".../bob-cli-lh/README.md",
        "sase-1ss.md",
        "+sase-1ss",
        "#sase-1ss",
        "%sase-1ss",
        "~sase-1ss",
        "sase--1ss",
        "sase-1ss-",
    ],
)
def test_rejection_cases_are_not_mentions(text: str) -> None:
    offset = text.find("sase-")
    if offset < 0:
        offset = text.find("bob-cli")
    if offset < 0:
        offset = 0
    assert bead_mention_at(text, offset) is None


def test_cursor_past_end_is_none() -> None:
    assert bead_mention_at("sase-1ss", 9) is None
    assert bead_mention_at("sase-1ss", -1) is None
