"""Tests for glossary preview card render helpers."""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

from rich.console import Console

from sase.ace.tui.modals.glossary_preview_render import (
    build_alias_chips,
    build_glossary_title,
    build_property_grid,
    glossary_definition_markdown,
    glossary_cross_references,
    glossary_source_display,
)
from sase.core.glossary_facade import GlossaryEntry


def _entry(
    index: int,
    term: str,
    *,
    definition: str = "Definition.",
    configured_aliases: tuple[str, ...] = (),
    display_aliases: tuple[str, ...] = (),
    effective_aliases: tuple[str, ...] | None = None,
    source: dict[str, Any] | None = None,
) -> GlossaryEntry:
    return GlossaryEntry(
        index=index,
        term=term,
        normalized_term=term.casefold(),
        definition=definition,
        configured_aliases=configured_aliases,
        display_aliases=display_aliases,
        effective_aliases=effective_aliases or (term.casefold(), *display_aliases),
        source=source,
    )


def _render_text(renderable: object) -> str:
    console = Console(file=io.StringIO(), width=100, record=True)
    console.print(renderable)
    return console.export_text()


def test_alias_chips_use_display_aliases_not_configured_aliases() -> None:
    entry = _entry(
        0,
        "Agent Clan",
        configured_aliases=("agent clans",),
        display_aliases=(),
        effective_aliases=("agent clan", "agent clans"),
    )

    assert build_alias_chips(entry.display_aliases, accent="#87D7FF") is None


def test_property_grid_omits_source_when_no_path_resolves() -> None:
    entry = _entry(0, "Agent Clan", source=None)
    catalog = SimpleNamespace(config_path=None)

    assert glossary_source_display(catalog, entry) is None
    text = _render_text(
        build_property_grid(
            entry,
            project_name="sase",
            source_display=None,
            effective_count=len(entry.effective_aliases),
        )
    )
    assert "Project" in text
    assert "Matches" in text
    assert "Source" not in text


def test_title_omits_matched_line_when_match_equals_term_case_insensitive() -> None:
    entry = _entry(0, "Agent Clan")

    text = _render_text(
        build_glossary_title(
            entry,
            matched_text="agent clan",
            project_name="sase",
            accent="#87D7FF",
        )
    )

    assert "Agent Clan" in text
    assert "matched" not in text


def test_title_omits_wrapped_match_after_whitespace_normalization() -> None:
    entry = _entry(0, "Agent Clan")

    text = _render_text(
        build_glossary_title(
            entry,
            matched_text="agent\n  clan",
            project_name="sase",
            accent="#87D7FF",
        )
    )

    assert "Agent Clan" in text
    assert "matched" not in text


def test_title_renders_wrapped_alias_match_on_one_line() -> None:
    entry = _entry(0, "Agent Clan")

    text = _render_text(
        build_glossary_title(
            entry,
            matched_text="agent\n  family",
            project_name="sase",
            accent="#87D7FF",
        )
    )

    assert 'matched "agent family"' in text
    assert "agent\n  family" not in text


def test_cross_references_drop_self_dedupe_and_preserve_order() -> None:
    entries = (
        _entry(0, "Agent Hood", definition="Agent Clan, Agent Lane, Agent Clan."),
        _entry(1, "Agent Lane"),
        _entry(2, "Agent Clan"),
    )
    catalog = SimpleNamespace(
        entries=entries,
        compiled=_CompiledGlossary(
            (
                _span(0, "Agent Hood"),
                _span(2, "Agent Clan"),
                _span(1, "Agent Lane"),
                _span(2, "Agent Clan"),
            )
        ),
    )

    assert glossary_cross_references(catalog, entries[0]) == (entries[2], entries[1])


def test_definition_markdown_links_non_self_references() -> None:
    entry = _entry(0, "Agent Hood", definition="See Agent Lane.")
    reference = _entry(1, "Agent Lane")
    catalog = SimpleNamespace(
        entries=(entry, reference),
        compiled=_CompiledGlossary((_span_at(1, "Agent Lane", start=4),)),
    )

    assert glossary_definition_markdown(catalog, entry) == (
        "See [Agent Lane](glossary:1)."
    )


def test_definition_markdown_normalizes_wrapped_link_text() -> None:
    entry = _entry(0, "Agent Hood", definition="See agent\n  lane.")
    reference = _entry(1, "Agent Lane")
    catalog = SimpleNamespace(
        entries=(entry, reference),
        compiled=_CompiledGlossary((_span_at(1, "agent\n  lane", start=4),)),
    )

    assert glossary_definition_markdown(catalog, entry) == (
        "See [agent lane](glossary:1)."
    )


def test_cross_references_cap_at_nine() -> None:
    entries = tuple(_entry(index, f"Term {index}") for index in range(12))
    catalog = SimpleNamespace(
        entries=entries,
        compiled=_CompiledGlossary(
            tuple(_span(index, f"Term {index}") for index in range(12))
        ),
    )

    references = glossary_cross_references(catalog, entries[0])

    assert references == entries[1:10]


class _CompiledGlossary:
    def __init__(self, spans: tuple[dict[str, Any], ...]) -> None:
        self._spans = spans

    def scan(self, _text: str) -> list[dict[str, Any]]:
        return list(self._spans)


def _span(entry_index: int, matched_text: str) -> dict[str, Any]:
    return _span_at(entry_index, matched_text, start=0)


def _span_at(entry_index: int, matched_text: str, *, start: int) -> dict[str, Any]:
    end = start + len(matched_text)
    return {
        "term": matched_text,
        "entry_index": entry_index,
        "alias_index": 0,
        "alias": matched_text,
        "matched_text": matched_text,
        "byte_start": start,
        "byte_end": end,
        "range": {
            "start": {"line": 0, "character": start},
            "end": {"line": 0, "character": end},
        },
        "segments": [
            {
                "byte_start": start,
                "byte_end": end,
                "range": {
                    "start": {"line": 0, "character": start},
                    "end": {"line": 0, "character": end},
                },
            }
        ],
    }
