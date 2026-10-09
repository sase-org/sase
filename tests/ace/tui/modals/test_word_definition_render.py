"""Tests for dictionary card rendering: text shape and losslessness."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from rich.console import Console

from sase.ace.tui.modals._word_definition_gcide import normalize_gcide_markup
from sase.ace.tui.modals.word_definition_card import (
    build_definition_card,
    infer_database,
)
from sase.ace.tui.modals.word_definition_render import (
    build_attribution,
    build_details,
    build_headline,
    build_lead,
    definition_card_palette,
)
from sase.core.word_lookup import _parse_definition_sections

_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dict"
_WORDS = ("refuting", "ephemeral", "loquacious", "serendipity", "run", "unix")
_TOKEN_RE = re.compile(r"[^\W\d_]{2,}")
_CITATION_RE = re.compile(r"^\[[^\[\]]+\]\s*$")
_MOBY_HEADER_RE = re.compile(r"^\d+\s+Moby Thesaurus words?\s+for\s+\".+\":\s*$")

_ACCENT = "#5FD7AF"
_PILL_FG = "#1a1a1a"


def _rendered_text(word: str) -> str:
    raw = (_FIXTURES / f"{word}.txt").read_text()
    card = build_definition_card(word, _parse_definition_sections(raw))
    console = Console(width=80, record=True, color_system=None)
    with console.capture() as capture:
        console.print(build_headline(card, accent=_ACCENT, pill_fg=_PILL_FG))
        if card.lead is not None:
            console.print(build_lead(card))
            console.print(build_attribution(card))
        console.print(build_details(card, accent=_ACCENT))
    return capture.get()


def test_headings_and_headword_render() -> None:
    text = _rendered_text("refuting")
    assert "WEBSTER'S 1913" in text
    assert "MOBY THESAURUS · 18 words" in text
    assert "refute" in text
    assert "{" not in text
    assert "}" not in text
    assert "[1913 Webster]" not in text


def test_hanging_indent_continuations_start_with_spaces() -> None:
    text = _rendered_text("run")
    lines = text.splitlines()
    # The Moby word list wraps: continuation lines begin with a space.
    wrapped = [line for line in lines if line.startswith(" ")]
    assert wrapped


def test_palette_dark_and_light() -> None:
    class Dark:
        dark = True

    class Light:
        dark = False

    assert definition_card_palette(Dark()) == ("#5FD7AF", "#1a1a1a")
    assert definition_card_palette(Light()) == ("#00875F", "#FFFFFF")


def _raw_tokens(body: str, database: str) -> set[str]:
    """Alphabetic tokens the render must preserve.

    Structural tokens are removed, matching the parser contract: GCIDE
    citation-tag lines, the Moby count header, the GCIDE ``Syn:`` label, the
    GCIDE ``as,`` usage marker (rendered examples drop it, as in the design
    target), WordNet bracket labels, and WordNet sense-line POS tags (folded
    into the ``noun``/``verb``/``adjective``/``adverb`` group headings).
    """
    tokens: set[str] = set()
    for line in body.splitlines():
        stripped = line.strip()
        if database == "gcide" and _CITATION_RE.match(
            normalize_gcide_markup(line).strip()
        ):
            continue
        if database == "moby-thesaurus" and _MOBY_HEADER_RE.match(stripped):
            continue
        normalized = normalize_gcide_markup(line).replace("{", " ").replace("}", " ")
        for token in _TOKEN_RE.findall(normalized.casefold()):
            if database == "gcide" and token in ("syn", "as"):
                continue
            if database == "wn" and token in (
                "syn",
                "ant",
                "also",
                "see",
                "adj",
                "adv",
            ):
                continue
            tokens.add(token)
    return tokens


@pytest.mark.parametrize("word", _WORDS)
def test_render_is_lossless(word: str) -> None:
    raw = (_FIXTURES / f"{word}.txt").read_text()
    sections = _parse_definition_sections(raw)
    rendered = set(_TOKEN_RE.findall(_rendered_text(word).casefold()))
    for section in sections:
        database = infer_database(section)
        missing = _raw_tokens(section.body, database) - rendered
        assert missing == set(), f"{word} [{database}] lost {sorted(missing)[:10]}"
