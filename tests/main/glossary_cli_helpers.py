"""Shared fixtures for ``sase glossary`` CLI handler tests."""

from __future__ import annotations

from typing import Any

from sase.core.glossary_facade import GlossaryCatalog, GlossaryEntry
from sase.glossary.cli_common import ResolvedGlossaryProject


class FakeCompiledGlossaryCatalog:
    """A fake compiled matcher keyed by exact definition text."""

    def __init__(
        self, spans_by_definition: dict[str, tuple[dict[str, Any], ...]]
    ) -> None:
        self._spans_by_definition = spans_by_definition

    def scan(self, text: str) -> list[dict[str, Any]]:
        return list(self._spans_by_definition.get(text, ()))


def glossary_entry(
    index: int,
    term: str,
    definition: str = "Definition.",
    *,
    aliases: tuple[str, ...] = (),
) -> GlossaryEntry:
    return GlossaryEntry(
        index=index,
        term=term,
        normalized_term=term.casefold(),
        definition=definition,
        configured_aliases=aliases,
        display_aliases=aliases,
        effective_aliases=(term, *aliases),
        source={"config_path": "sase/sase.yml"},
    )


def glossary_span(
    entry_index: int, matched_text: str, *, start: int = 0
) -> dict[str, Any]:
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


def resolved_glossary_project(
    *,
    project_name: str = "sase",
    entries: tuple[GlossaryEntry, ...],
    compiled: FakeCompiledGlossaryCatalog | None = None,
) -> ResolvedGlossaryProject:
    return ResolvedGlossaryProject(
        project_name=project_name,
        catalog=GlossaryCatalog(schema_version=1, entries=entries),
        compiled=compiled or FakeCompiledGlossaryCatalog({}),
        config_path="/tmp/sase/sase/sase.yml",
    )


def diamond_resolved_glossary_project() -> ResolvedGlossaryProject:
    alpha = glossary_entry(0, "Alpha", "Mentions Beta then Gamma.")
    beta = glossary_entry(1, "Beta", "Mentions Delta.", aliases=("B",))
    gamma = glossary_entry(2, "Gamma", "Mentions Delta.")
    delta = glossary_entry(3, "Delta", "A leaf.")
    compiled = FakeCompiledGlossaryCatalog(
        {
            alpha.definition: (
                glossary_span(1, "Beta", start=9),
                glossary_span(2, "Gamma", start=19),
            ),
            beta.definition: (glossary_span(3, "Delta", start=9),),
            gamma.definition: (glossary_span(3, "Delta", start=9),),
        }
    )
    return resolved_glossary_project(
        entries=(alpha, beta, gamma, delta), compiled=compiled
    )
