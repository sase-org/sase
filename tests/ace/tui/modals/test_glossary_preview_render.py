"""Tests for glossary preview card render helpers."""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

from rich.console import Console

from sase.ace.tui.modals.glossary_preview_render import (
    build_alias_chips,
    build_glossary_title,
    build_numbered_chip_rows,
    build_property_grid,
    glossary_definition_markdown,
    glossary_definition_position,
    glossary_cross_references,
    glossary_reference_spans,
    glossary_source_display,
)
from sase.core.glossary_facade import GlossaryEntry
from sase.memory.web.closure import GlossaryDefinitionLink


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


def test_source_helpers_accept_v1_and_v2_source_payloads() -> None:
    catalog = SimpleNamespace(config_path=None)
    v1_entry = _entry(
        0,
        "Agent Clan",
        source={
            "config_path": "/repo/sase/sase.yml",
            "definition_range": {
                "start": {"line": 4, "character": 16},
                "end": {"line": 4, "character": 27},
            },
        },
    )
    v2_entry = _entry(
        1,
        "Memory Web",
        source={
            "source_path": "/repo/sase/memory/glossary/memory-web.md",
            "body_range": {
                "start": {"line": 8, "character": 0},
                "end": {"line": 10, "character": 9},
            },
        },
    )

    assert glossary_source_display(catalog, v1_entry) == "/repo/sase/sase.yml:5:17"
    assert glossary_definition_position(v1_entry) == (5, 17)
    assert glossary_source_display(catalog, v2_entry) == (
        "/repo/sase/memory/glossary/memory-web.md:9:1"
    )
    assert glossary_definition_position(v2_entry) == (9, 1)


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
            matched_text="agent\n  group",
            project_name="sase",
            accent="#87D7FF",
        )
    )

    assert 'matched "agent group"' in text
    assert "agent\n  group" not in text


def test_numbered_chip_rows_share_renderer_for_parent_children_labels() -> None:
    text = _render_text(
        build_numbered_chip_rows(
            (
                ("PARENT", ("hub",)),
                ("CHILDREN", ("grand",)),
            ),
            focused_number=2,
            accent="#87D7FF",
        )
    )

    assert "PARENT" in text
    assert "CHILDREN" in text
    assert "1 hub" in text
    assert "2 grand" in text
    assert ".1 hub" not in text


def test_numbered_chip_rows_render_optional_shortcut_prefix() -> None:
    text = _render_text(
        build_numbered_chip_rows(
            (
                ("SEE ALSO", ("Beta", "Gamma")),
                ("REFERENCED BY", ("Delta",)),
            ),
            focused_number=None,
            accent="#87D7FF",
            shortcut_prefix=".",
        )
    )

    assert ".1 Beta" in text
    assert ".2 Gamma" in text
    assert ".3 Delta" in text


def test_cross_references_drop_self_dedupe_and_preserve_order() -> None:
    entries = (
        _entry(0, "Agent Hood", definition="Agent Clan, Sase Agent, Agent Clan."),
        _entry(1, "Sase Agent"),
        _entry(2, "Agent Clan"),
    )
    catalog = SimpleNamespace(
        entries=entries,
        compiled=_CompiledGlossary(
            (
                _span(0, "Agent Hood"),
                _span(2, "Agent Clan"),
                _span(1, "Sase Agent"),
                _span(2, "Agent Clan"),
            )
        ),
    )

    assert glossary_cross_references(catalog, entries[0]) == (entries[2], entries[1])


def test_definition_markdown_links_non_self_references() -> None:
    entry = _entry(0, "Agent Hood", definition="See Sase Agent.")
    reference = _entry(1, "Sase Agent")
    catalog = SimpleNamespace(
        entries=(entry, reference),
        compiled=_CompiledGlossary((_span_at(1, "Sase Agent", start=4),)),
    )

    assert glossary_definition_markdown(catalog, entry) == (
        "See [Sase Agent](glossary:1)."
    )


def test_definition_markdown_normalizes_wrapped_link_text() -> None:
    entry = _entry(0, "Agent Hood", definition="See sase\n  agent.")
    reference = _entry(1, "Sase Agent")
    catalog = SimpleNamespace(
        entries=(entry, reference),
        compiled=_CompiledGlossary((_span_at(1, "sase\n  agent", start=4),)),
    )

    assert glossary_definition_markdown(catalog, entry) == (
        "See [sase agent](glossary:1)."
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


def _link(
    definition: str,
    raw: str,
    target: str,
    target_index: int | None,
    *,
    occurrence: int = 0,
) -> GlossaryDefinitionLink:
    start = -1
    for _ in range(occurrence + 1):
        start = definition.index(raw, start + 1)
    return GlossaryDefinitionLink(
        raw=raw,
        target=target,
        byte_start=start,
        byte_end=start + len(raw),
        target_index=target_index,
    )


def _linked_catalog(
    entries: tuple[GlossaryEntry, ...],
    links: tuple[GlossaryDefinitionLink, ...],
    mentions: tuple[dict[str, Any], ...] = (),
) -> SimpleNamespace:
    return SimpleNamespace(
        entries=entries,
        compiled=_CompiledGlossary(mentions),
        definition_links={entries[0].index: links},
    )


def test_cross_references_include_link_targets_no_phrase_matches() -> None:
    definition = "Depends on [[project-note]]."
    entries = (
        _entry(0, "Task Successor", definition=definition),
        _entry(1, "Project Note"),
    )
    catalog = _linked_catalog(
        entries, (_link(definition, "[[project-note]]", "project-note", 1),)
    )

    assert glossary_cross_references(catalog, entries[0]) == (entries[1],)


def test_cross_references_put_authored_links_before_mentions() -> None:
    definition = "Mentions Beta Term, then links [[gamma]] and [[delta]]."
    entries = (
        _entry(0, "Alpha", definition=definition),
        _entry(1, "Beta Term"),
        _entry(2, "Gamma"),
        _entry(3, "Delta"),
    )
    catalog = _linked_catalog(
        entries,
        (
            _link(definition, "[[gamma]]", "gamma", 2),
            _link(definition, "[[delta]]", "delta", 3),
        ),
        mentions=(_span_at(1, "Beta Term", start=definition.index("Beta Term")),),
    )

    assert glossary_cross_references(catalog, entries[0]) == (
        entries[2],
        entries[3],
        entries[1],
    )


def test_cross_references_link_order_follows_first_link_and_dedupes() -> None:
    definition = "[[delta]] [[gamma]] [[delta]]"
    entries = (
        _entry(0, "Alpha", definition=definition),
        _entry(1, "Gamma"),
        _entry(2, "Delta"),
    )
    catalog = _linked_catalog(
        entries,
        (
            _link(definition, "[[delta]]", "delta", 2),
            _link(definition, "[[gamma]]", "gamma", 1),
            _link(definition, "[[delta]]", "delta", 2, occurrence=1),
        ),
    )

    assert glossary_cross_references(catalog, entries[0]) == (entries[2], entries[1])


def test_cross_references_cap_at_nine_keeps_links_over_mentions() -> None:
    mention_text = " ".join(f"Term {i}" for i in range(1, 10))
    definition = f"{mention_text} [[Linked]]"
    entries = (
        _entry(0, "Alpha", definition=definition),
        *(_entry(i, f"Term {i}") for i in range(1, 10)),
        _entry(10, "Linked"),
    )
    catalog = _linked_catalog(
        entries,
        (_link(definition, "[[Linked]]", "Linked", 10),),
        mentions=tuple(
            _span_at(i, f"Term {i}", start=definition.index(f"Term {i}"))
            for i in range(1, 10)
        ),
    )

    references = glossary_cross_references(catalog, entries[0])

    assert len(references) == 9
    assert references[0] is entries[10]
    assert references[1:] == entries[1:9]


def test_definition_markdown_turns_resolved_links_into_term_links() -> None:
    definition = "See [[project-note]] and [[glossary:failure-signature]]s."
    entries = (
        _entry(0, "Task Successor", definition=definition),
        _entry(1, "Project Note"),
        _entry(2, "Failure Signature"),
    )
    catalog = _linked_catalog(
        entries,
        (
            _link(definition, "[[project-note]]", "project-note", 1),
            _link(
                definition,
                "[[glossary:failure-signature]]",
                "glossary:failure-signature",
                2,
            ),
        ),
    )

    assert glossary_definition_markdown(catalog, entries[0]) == (
        "See [Project Note](glossary:1) and [Failure Signature](glossary:2)s."
    )


def test_definition_markdown_does_not_hyperlink_mentions_inside_links() -> None:
    definition = "Goal: [[glossary:Proc]] and [[decisions/goal-ledger]] here."
    entries = (
        _entry(0, "Receipt", definition=definition),
        _entry(1, "Proc"),
        _entry(2, "goal"),
    )
    catalog = _linked_catalog(
        entries,
        (
            _link(definition, "[[glossary:Proc]]", "glossary:Proc", 1),
            _link(
                definition, "[[decisions/goal-ledger]]", "decisions/goal-ledger", None
            ),
        ),
        mentions=(
            _span_at(1, "Proc", start=definition.index("Proc")),
            _span_at(2, "goal", start=definition.index("goal-ledger")),
        ),
    )

    assert glossary_definition_markdown(catalog, entries[0]) == (
        "Goal: [Proc](glossary:1) and [[decisions/goal-ledger]] here."
    )
    assert glossary_cross_references(catalog, entries[0]) == (entries[1],)


def test_definition_markdown_renders_self_link_as_plain_term_text() -> None:
    definition = "I am [[alpha-term]] and see [[beta]]."
    entries = (
        _entry(0, "Alpha Term", definition=definition),
        _entry(1, "Beta"),
    )
    catalog = _linked_catalog(
        entries,
        (
            _link(definition, "[[alpha-term]]", "alpha-term", 0),
            _link(definition, "[[beta]]", "beta", 1),
        ),
    )

    assert glossary_definition_markdown(catalog, entries[0]) == (
        "I am Alpha Term and see [Beta](glossary:1)."
    )
    assert glossary_cross_references(catalog, entries[0]) == (entries[1],)


def test_foreign_and_unresolved_links_stay_verbatim() -> None:
    definition = "Read [[decisions/x]], ![[nope]] and [[foo.md]]."
    entries = (_entry(0, "Alpha", definition=definition),)
    catalog = _linked_catalog(
        entries,
        (
            _link(definition, "[[decisions/x]]", "decisions/x", None),
            _link(definition, "![[nope]]", "nope", None),
            _link(definition, "[[foo.md]]", "foo.md", None),
        ),
    )

    assert glossary_reference_spans(catalog, entries[0]) == ()
    assert glossary_definition_markdown(catalog, entries[0]) == definition
    assert glossary_cross_references(catalog, entries[0]) == ()


def test_catalog_without_definition_links_behaves_as_before() -> None:
    definition = "See Sase Agent and [[sase-agent]]."
    entries = (
        _entry(0, "Agent Hood", definition=definition),
        _entry(1, "Sase Agent"),
    )
    catalog = SimpleNamespace(
        entries=entries,
        compiled=_CompiledGlossary((_span_at(1, "Sase Agent", start=4),)),
    )

    assert glossary_cross_references(catalog, entries[0]) == (entries[1],)
    assert glossary_definition_markdown(catalog, entries[0]) == (
        "See [Sase Agent](glossary:1) and [[sase-agent]]."
    )


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
