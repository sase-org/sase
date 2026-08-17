"""Tests for inbound glossary reverse references."""

from __future__ import annotations

from sase.core.glossary_facade import (
    build_glossary_catalog,
    compile_glossary_catalog,
)
from sase.glossary.relations import glossary_reverse_references


def test_reverse_references_drop_self_and_keep_inbound_order() -> None:
    inputs = [
        {
            "term": "Alpha",
            "definition": "Alpha mentions Beta and then Alpha again.",
        },
        {"term": "Beta", "definition": "A leaf."},
        {"term": "Gamma", "definition": "Gamma also mentions Beta."},
        {"term": "Delta", "definition": "Unrelated leaf."},
    ]
    catalog = build_glossary_catalog(inputs)
    compiled = compile_glossary_catalog(inputs)

    reverse = glossary_reverse_references(catalog, compiled)
    by_term = {entry.term: reverse[entry.index] for entry in catalog.entries}

    assert by_term["Alpha"] == ()
    assert by_term["Beta"] == ("Alpha", "Gamma")
    assert by_term["Gamma"] == ()
    assert by_term["Delta"] == ()
    assert "Alpha" not in by_term["Alpha"]
