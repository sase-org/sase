"""Tests for the pure dictionary definition card builders."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.modals._word_definition_gcide import (
    normalize_gcide_markup,
    parse_gcide_body,
)
from sase.ace.tui.modals.word_definition_card import (
    build_definition_card,
    infer_database,
    parse_moby_body,
    parse_wordnet_body,
    source_display_label,
)
from sase.core.word_lookup import DefinitionSection
from sase.core.word_lookup import _parse_definition_sections

_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dict"


def _load(word: str) -> tuple[DefinitionSection, ...]:
    return _parse_definition_sections((_FIXTURES / f"{word}.txt").read_text())


def test_refuting_lead_is_gcide_first_sense() -> None:
    card = build_definition_card("refuting", _load("refuting"))

    assert card.headword == "refute"
    assert card.pos_display == "transitive verb"
    assert card.syllables == "re·fute′"
    assert card.show_looked_up is True
    assert card.lead is not None
    assert card.lead.gloss.startswith("To disprove and overthrow")
    assert card.lead.examples[0].startswith("to refute arguments")
    assert card.lead.source_label == "Webster's 1913"


def test_ephemeral_lead_is_wordnet_adjective() -> None:
    card = build_definition_card("ephemeral", _load("ephemeral"))

    assert card.lead is not None
    assert card.lead.gloss.startswith("lasting a very short time")
    assert card.pos_display == "adjective"
    assert card.syllables == "e·phem′er·al"
    assert card.lead.sense_total == 2


def test_run_lead_aligns_to_gcide_verb() -> None:
    card = build_definition_card("run", _load("run"))

    assert card.lead is not None
    assert card.lead.source_label == "WordNet"
    assert card.pos_display == "verb"
    assert "feet" in card.lead.gloss


def test_serendipity_lead_has_no_syllables() -> None:
    card = build_definition_card("serendipity", _load("serendipity"))

    assert card.lead is not None
    assert card.syllables == ""
    assert "fortunate discoveries" in card.lead.gloss


def test_unix_headword_keeps_wordnet_case() -> None:
    card = build_definition_card("unix", _load("unix"))

    assert card.headword == "UNIX"
    assert card.show_looked_up is False
    assert card.lead is not None
    assert "operating system" in card.lead.gloss


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("r['e]futer", "réfuter"),
        ("Zo[`o]l", "Zoòl"),
        ('Ne["e]d', "Neëd"),
        ("t[^e]te", "tête"),
        ("se[~n]or", "señor"),
        ("fa[,c]ade", "façade"),
        ("[ae]ther", "æther"),
        ("[OE]uvre", "Œuvre"),
        ("[root]2", "√2"),
        ("f[=u]t", "fūt"),
        ("r[u^]n", "rŭn"),
    ],
)
def test_gcide_markup_table(token: str, expected: str) -> None:
    assert normalize_gcide_markup(token) == expected


def test_gcide_unknown_tokens_survive_verbatim() -> None:
    assert normalize_gcide_markup("a [bogus] b [x^y] c") == "a [bogus] b [x^y] c"


def test_gcide_citation_lines_are_dropped() -> None:
    body = "  Foo \\Foo\\, n.\n     A thing.\n     [1913 Webster]\n\n     More.\n"
    entry = parse_gcide_body(body)
    assert all("[1913 Webster]" not in block.text for block in entry.blocks)


def test_gcide_wrapped_quote_attribution_joins() -> None:
    card = build_definition_card("ephemeral", _load("ephemeral"))
    authors = [
        block.author
        for entry in card.entries
        for block in entry.blocks
        if block.kind == "quote" and block.author
    ]
    assert "Sir J. Stephen" in authors


def test_gcide_quote_attribution_simple() -> None:
    card = build_definition_card("refuting", _load("refuting"))
    authors = [
        block.author
        for entry in card.entries
        for block in entry.blocks
        if block.kind == "quote"
    ]
    assert "Addison" in authors


def test_wordnet_syn_ant_extraction_filters_headword() -> None:
    headword, senses, _ = parse_wordnet_body(
        '  loquacious\n      adj 1: full of trivial conversation; "kept home"\n'
        "             [syn: {chatty}, {loquacious}] [ant: {taciturn}]"
    )
    assert headword == "loquacious"
    assert senses[0].synonyms == ("chatty",)
    assert senses[0].antonyms == ("taciturn",)
    assert senses[0].examples == ("kept home",)


def test_moby_count_and_items() -> None:
    count, items = parse_moby_body(
        '  3 Moby Thesaurus words for "x":\n     alpha, beta,\n     gamma\n'
    )
    assert count == 3
    assert items == ("alpha", "beta", "gamma")


def test_moby_heading_carries_count() -> None:
    card = build_definition_card("refuting", _load("refuting"))
    headings = [entry.heading for entry in card.entries]
    assert "MOBY THESAURUS · 18 words" in headings


def test_consecutive_gcide_sections_share_one_heading() -> None:
    card = build_definition_card("run", _load("run"))
    gcide_entries = [entry for entry in card.entries if entry.database == "gcide"]
    assert len(gcide_entries) == 1
    assert gcide_entries[0].heading == "WEBSTER'S 1913"


def test_database_inference_from_source_names() -> None:
    assert (
        infer_database(
            DefinitionSection(
                source="The Collaborative International Dictionary of English v.0.54",
                body="b",
            )
        )
        == "gcide"
    )
    assert infer_database(DefinitionSection(source="WordNet (r) 3.0", body="b")) == "wn"
    assert (
        infer_database(DefinitionSection(source="Moby Thesaurus II", body="b"))
        == "moby-thesaurus"
    )
    assert infer_database(DefinitionSection(source="Something Else", body="b")) == ""


def test_source_display_labels() -> None:
    assert source_display_label("gcide", "anything") == "Webster's 1913"
    assert source_display_label("wn", "anything") == "WordNet"
    assert source_display_label("moby-thesaurus", "anything") == "Moby Thesaurus"
    assert source_display_label("", "Custom Source") == "Custom Source"


def test_failing_parser_falls_back_without_losing_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.modals.word_definition_card as card_module

    def _raise(_body: str) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(card_module, "parse_gcide_body", _raise)
    sections = (
        DefinitionSection(source="GCIDE", database="gcide", body="  vital words here"),
    )
    card = build_definition_card("vital", sections)
    rendered_words = " ".join(
        block.text for entry in card.entries for block in entry.blocks
    )
    assert "vital words here" in rendered_words


def test_build_card_is_total_on_garbage() -> None:
    for body in (
        "",
        "   \n  \n",
        "  n 1: a greeting",
        "unbalanced [ brace { and \\ backslash",
    ):
        card = build_definition_card(
            "word", (DefinitionSection(source="X", body=body),)
        )
        assert card.headword
        assert isinstance(card.entries, tuple)


def test_gcide_entry_without_numbers_counts_one_sense() -> None:
    entry = parse_gcide_body(_load("refuting")[0].body)
    assert entry.first_sense_gloss.startswith("To disprove and overthrow")
    assert entry.first_sense_examples[0].startswith("to refute arguments")


__all__: list[str] = []
