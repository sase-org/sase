"""Tests for Textual-free bead-mention recognition."""

from __future__ import annotations

import pytest

from sase.bead.mentions import bead_mention_at, scan_bead_mentions


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


_OWNED = frozenset({"sase", "bob-cli"})


def test_scan_finds_bare_ids_only_for_owned_prefixes() -> None:
    text = "see sase-1ss and sase-1ss.1 here"
    mentions = scan_bead_mentions(text, _OWNED)
    assert [(m.bead_id, m.form) for m in mentions] == [
        ("sase-1ss", "bare"),
        ("sase-1ss.1", "bare"),
    ]
    assert all(text[m.start : m.end] == m.bead_id for m in mentions)


def test_scan_skips_unowned_prefixes() -> None:
    assert scan_bead_mentions("cash-flow stays plain", _OWNED) == ()
    assert scan_bead_mentions("see well-known-1a here", _OWNED) == ()
    assert scan_bead_mentions("see bob-cli-kx here", frozenset({"sase"})) == ()


def test_scan_prefix_matching_is_casefolded() -> None:
    mentions = scan_bead_mentions("see sase-1ss here", frozenset({"SASE"}))
    assert [m.bead_id for m in mentions] == ["sase-1ss"]


def test_scan_reuses_bare_rejection_rules() -> None:
    assert scan_bead_mentions("src/sase-1ss/x", _OWNED) == ()
    assert scan_bead_mentions("sase-1ss.md", _OWNED) == ()
    assert scan_bead_mentions("+sase-1ss", _OWNED) == ()
    assert scan_bead_mentions("sase--1ss", _OWNED) == ()
    assert scan_bead_mentions("%wait:sase-1ss", _OWNED)[0].bead_id == "sase-1ss"


def test_scan_covers_refs_and_skips_nested_bare_duplicates() -> None:
    mentions = scan_bead_mentions("@bead:sase-1ss and bead:bob-cli-kx.", _OWNED)
    assert [(m.bead_id, m.form, m.start, m.end) for m in mentions] == [
        ("sase-1ss", "ref", 0, 14),
        ("bob-cli-kx", "ref", 19, 34),
    ]


def test_scan_returns_mentions_sorted_by_offset() -> None:
    mentions = scan_bead_mentions("sase-1ss.2 then @bead:bob-cli-kx", _OWNED)
    assert [m.bead_id for m in mentions] == ["sase-1ss.2", "bob-cli-kx"]
    assert mentions[0].form == "bare"
    assert mentions[1].form == "ref"


def test_scan_empty_text_or_prefixes_is_empty() -> None:
    assert scan_bead_mentions("", _OWNED) == ()
    assert scan_bead_mentions("see sase-1ss", frozenset()) == ()
    assert scan_bead_mentions("   ", _OWNED) == ()
