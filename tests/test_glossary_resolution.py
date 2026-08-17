"""Tests for shared glossary lookup and reference-closure resolution."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.modals.glossary_preview_render import glossary_cross_references
from sase.core.glossary_facade import (
    GlossaryCatalog,
    GlossaryEntry,
    GlossarySpan,
    build_glossary_catalog,
    compile_glossary_catalog,
)
from sase.glossary.resolution import (
    GlossaryLookupError,
    normalize_glossary_reference,
    resolve_glossary_closure,
)


def _lookup(catalog: GlossaryCatalog, reference: str) -> GlossaryEntry:
    """Resolve one reference through the closure entry point callers use."""
    return resolve_glossary_closure(catalog, None, (reference,), depth=0).roots[0]


def test_normalize_glossary_reference_collapses_separators() -> None:
    assert normalize_glossary_reference("Agent Hood") == "agent hood"
    assert normalize_glossary_reference("agent-hood") == "agent hood"
    assert normalize_glossary_reference("agent_hood") == "agent hood"
    assert normalize_glossary_reference("  Agent   Hood  ") == "agent hood"


def test_lookup_resolves_alias_plural_prefix_and_slug_forms() -> None:
    catalog = _catalog(
        _entry(
            0,
            "Agent Hood",
            effective=("Agent Hood", "hood", "agent neighborhood", "Agent Hoods"),
        ),
        _entry(1, "Widget Box", effective=("Widget Box", "Widget Boxes")),
        _entry(2, "Sase Agent", effective=("Sase Agent", "agent")),
    )

    assert _lookup(catalog, "hood").term == "Agent Hood"
    assert _lookup(catalog, "Widget Boxes").term == "Widget Box"
    assert _lookup(catalog, "widget b").term == "Widget Box"
    assert _lookup(catalog, "agent-hood").term == "Agent Hood"
    assert _lookup(catalog, "agent_hood").term == "Agent Hood"


def test_lookup_unknown_and_ambiguous_references_include_candidates() -> None:
    catalog = _catalog(
        _entry(0, "Widget Box"),
        _entry(1, "Widget Factory"),
        _entry(2, "Alpha Foo"),
        _entry(3, "Beta Foo"),
        _entry(4, "Gamma Foo"),
        _entry(5, "Delta Foo"),
        _entry(6, "Epsilon Foo"),
        _entry(7, "Zeta Foo"),
        _entry(8, "Eta Foo"),
    )

    with pytest.raises(
        GlossaryLookupError, match="did you mean: Widget Box"
    ) as unknown:
        _lookup(catalog, "box")
    assert unknown.value.reference == "box"
    assert unknown.value.candidates == ("Widget Box",)

    with pytest.raises(GlossaryLookupError, match="unknown glossary term: widget"):
        _lookup(catalog, "widget")

    with pytest.raises(GlossaryLookupError) as missing:
        _lookup(catalog, "xyzzy")
    assert missing.value.candidates == ()

    with pytest.raises(GlossaryLookupError) as crowded:
        _lookup(catalog, "foo")
    assert crowded.value.candidates == (
        "Alpha Foo",
        "Beta Foo",
        "Gamma Foo",
        "Delta Foo",
        "Epsilon Foo",
    )


def test_closure_over_diamond_records_both_referrers() -> None:
    alpha = _entry(0, "Alpha", definition="Mentions Beta then Gamma.")
    beta = _entry(1, "Beta", definition="Mentions Delta.")
    gamma = _entry(2, "Gamma", definition="Mentions Delta.")
    delta = _entry(3, "Delta", definition="A leaf.")
    catalog = _catalog(alpha, beta, gamma, delta)
    compiled = _Compiled(
        {
            alpha.definition: (
                _span(1, "Beta", start=9),
                _span(2, "Gamma", start=19),
            ),
            beta.definition: (_span(3, "Delta", start=9),),
            gamma.definition: (_span(3, "Delta", start=9),),
        }
    )

    closure = resolve_glossary_closure(catalog, compiled, ("Alpha",))

    assert [node.entry.term for node in closure.nodes] == [
        "Alpha",
        "Beta",
        "Gamma",
        "Delta",
    ]
    assert closure.nodes[0].origin == "requested"
    assert closure.nodes[3].origin == "related"
    assert closure.nodes[3].depth == 2
    assert closure.nodes[3].referrer is not None
    assert closure.nodes[3].referrer.term == "Beta"
    assert closure.nodes[3].referrer.matched_text == "Delta"
    assert closure.nodes[3].also_referenced_by == ("Gamma",)
    assert closure.truncated is False


def test_closure_cycle_keeps_requested_origin() -> None:
    alpha = _entry(0, "Alpha", definition="See Beta.")
    beta = _entry(1, "Beta", definition="See Alpha.")
    catalog = _catalog(alpha, beta)
    compiled = _Compiled(
        {
            alpha.definition: (_span(1, "Beta", start=4),),
            beta.definition: (_span(0, "Alpha", start=4),),
        }
    )

    closure = resolve_glossary_closure(catalog, compiled, ("Alpha",))

    assert [node.entry.term for node in closure.nodes] == ["Alpha", "Beta"]
    assert closure.nodes[0].origin == "requested"
    assert closure.nodes[0].also_referenced_by == ("Beta",)
    assert closure.nodes[1].origin == "related"
    assert closure.truncated is False


def test_closure_depth_limits_and_truncation() -> None:
    alpha = _entry(0, "Alpha", definition="See Beta.")
    beta = _entry(1, "Beta", definition="See Gamma.")
    gamma = _entry(2, "Gamma", definition="A leaf.")
    catalog = _catalog(alpha, beta, gamma)
    compiled = _Compiled(
        {
            alpha.definition: (_span(1, "Beta", start=4),),
            beta.definition: (_span(2, "Gamma", start=4),),
        }
    )

    depth0 = resolve_glossary_closure(catalog, compiled, ("Alpha",), depth=0)
    depth1 = resolve_glossary_closure(catalog, compiled, ("Alpha",), depth=1)
    unlimited = resolve_glossary_closure(catalog, compiled, ("Alpha",))

    assert [node.entry.term for node in depth0.nodes] == ["Alpha"]
    assert depth0.truncated is True
    assert [node.entry.term for node in depth1.nodes] == ["Alpha", "Beta"]
    assert depth1.truncated is True
    assert [node.entry.term for node in unlimited.nodes] == ["Alpha", "Beta", "Gamma"]
    assert unlimited.truncated is False
    assert unlimited.depth_limit is None


def test_closure_multi_root_order_and_requested_origin() -> None:
    alpha = _entry(0, "Alpha", definition="See Beta.")
    beta = _entry(1, "Beta", definition="See Gamma.")
    gamma = _entry(2, "Gamma", definition="A leaf.")
    catalog = _catalog(alpha, beta, gamma)
    compiled = _Compiled(
        {
            alpha.definition: (_span(1, "Beta", start=4),),
            beta.definition: (_span(2, "Gamma", start=4),),
        }
    )

    closure = resolve_glossary_closure(catalog, compiled, ("Gamma", "Alpha"))

    assert [node.entry.term for node in closure.nodes] == ["Gamma", "Alpha", "Beta"]
    assert [node.origin for node in closure.nodes] == [
        "requested",
        "requested",
        "related",
    ]
    assert closure.roots == (gamma, alpha)
    assert closure.nodes[0].also_referenced_by == ("Beta",)


def test_closure_is_deterministic_across_repeated_runs() -> None:
    alpha = _entry(0, "Alpha", definition="See Beta and Gamma.")
    beta = _entry(1, "Beta", definition="See Gamma.")
    gamma = _entry(2, "Gamma", definition="A leaf.")
    catalog = _catalog(alpha, beta, gamma)
    compiled = _Compiled(
        {
            alpha.definition: (
                _span(1, "Beta", start=4),
                _span(2, "Gamma", start=13),
            ),
            beta.definition: (_span(2, "Gamma", start=4),),
        }
    )

    first = resolve_glossary_closure(catalog, compiled, ("Alpha",))
    second = resolve_glossary_closure(catalog, compiled, ("Alpha",))

    assert first == second


def test_glossary_cross_references_uses_shared_resolver_and_spans_fast_path() -> None:
    entries = (
        _entry(0, "Agent Hood", definition="Agent Clan, Sase Agent."),
        _entry(1, "Sase Agent"),
        _entry(2, "Agent Clan"),
        _entry(3, "Wrong"),
    )
    catalog = SimpleNamespace(
        entries=entries,
        compiled=_Compiled({entries[0].definition: (_span(3, "Wrong"),)}),
    )
    spans = (
        GlossarySpan.from_wire(_span(2, "Agent Clan", start=0)),
        GlossarySpan.from_wire(_span(1, "Sase Agent", start=12)),
    )

    assert glossary_cross_references(catalog, entries[0], spans=spans) == (
        entries[2],
        entries[1],
    )


def test_closure_uses_rust_matcher_for_plural_and_slug_roots() -> None:
    inputs = [
        {
            "term": "Agent Hood",
            "definition": "A group of sase agents.",
            "aliases": ["hood"],
        },
        {
            "term": "Sase Agent",
            "definition": "An agent.",
            "aliases": ["agent"],
        },
        {"term": "Widget Box", "definition": "A box."},
    ]
    catalog = build_glossary_catalog(inputs)
    compiled = compile_glossary_catalog(inputs)

    assert _lookup(catalog, "agent-hood").term == "Agent Hood"
    assert _lookup(catalog, "widget boxes").term == "Widget Box"

    closure = resolve_glossary_closure(catalog, compiled, ("agent_hood",))
    related = [node.entry.term for node in closure.nodes if node.origin == "related"]
    assert closure.roots[0].term == "Agent Hood"
    assert related == ["Sase Agent"]
    assert closure.nodes[1].referrer is not None
    assert closure.nodes[1].referrer.matched_text == "sase agents"


def _catalog(*entries: GlossaryEntry) -> GlossaryCatalog:
    return GlossaryCatalog(schema_version=1, entries=entries)


def _entry(
    index: int,
    term: str,
    definition: str = "Definition.",
    *,
    effective: tuple[str, ...] | None = None,
) -> GlossaryEntry:
    aliases = () if effective is None else effective[1:]
    return GlossaryEntry(
        index=index,
        term=term,
        normalized_term=term,
        definition=definition,
        configured_aliases=aliases,
        display_aliases=aliases,
        effective_aliases=effective or (term,),
        source=None,
    )


class _Compiled:
    def __init__(
        self, spans_by_definition: dict[str, tuple[dict[str, Any], ...]]
    ) -> None:
        self._spans_by_definition = spans_by_definition

    def scan(self, text: str) -> list[dict[str, Any]]:
        return list(self._spans_by_definition.get(text, ()))


def _span(entry_index: int, matched_text: str, *, start: int = 0) -> dict[str, Any]:
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
