"""Tests for the Rust-backed glossary facade."""

from __future__ import annotations

from typing import Any

from sase.core import glossary_facade as glossary


def test_glossary_facade_normalizes_catalog_entries(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def fake_binding(name: str):
        assert name == "glossary_catalog"

        def call(entries: list[dict[str, Any]]) -> dict[str, Any]:
            seen["entries"] = entries
            return {
                "schema_version": 1,
                "entries": [
                    {
                        "index": 0,
                        "term": "Agent Clan",
                        "normalized_term": "Agent Clan",
                        "definition": "A clan.",
                        "configured_aliases": ["agent clans"],
                        "display_aliases": [],
                        "effective_aliases": ["Agent Clan", "agent clans"],
                    }
                ],
            }

        return call

    monkeypatch.setattr(glossary, "require_rust_binding", fake_binding)

    catalog = glossary.build_glossary_catalog(
        [
            glossary.GlossaryInputEntry(
                term="Agent Clan",
                definition="A clan.",
                aliases=("agent clans",),
                source=glossary.GlossarySource(
                    config_path="/repo/sase/sase.yml",
                    config_key_path=("memory", "glossary", "Agent Clan"),
                ),
            )
        ]
    )

    assert seen["entries"][0]["source"]["config_path"] == "/repo/sase/sase.yml"
    assert catalog.entries[0].display_aliases == ()
    assert catalog.entries[0].effective_aliases == ("Agent Clan", "agent clans")


def test_glossary_facade_compiled_catalog_matches_derived_plural() -> None:
    handle = glossary.compile_glossary_catalog(
        [{"term": "Widget Box", "definition": "A widget container."}]
    )

    spans = glossary.scan_glossary_spans(handle, "Inspect the Widget Boxes today.")

    assert spans
    assert spans[0].term == "Widget Box"
    assert spans[0].alias == "Widget Boxes"
    assert spans[0].matched_text == "Widget Boxes"


def test_glossary_facade_scans_and_looks_up_with_compiled_handle(monkeypatch) -> None:
    span = {
        "term": "Agent Clan",
        "entry_index": 0,
        "alias_index": 0,
        "alias": "Agent Clan",
        "matched_text": "agent clan",
        "byte_start": 4,
        "byte_end": 14,
        "range": {
            "start": {"line": 0, "character": 4},
            "end": {"line": 0, "character": 14},
        },
    }

    class FakeHandle:
        def scan(self, text: str) -> list[dict[str, Any]]:
            assert text == "see agent clan"
            return [span]

        def lookup(self, text: str, line: int, character: int) -> dict[str, Any] | None:
            assert (text, line, character) == ("see agent clan", 0, 5)
            return span

    def fake_binding(name: str):
        assert name == "compile_glossary_catalog"
        return lambda entries: FakeHandle()

    monkeypatch.setattr(glossary, "require_rust_binding", fake_binding)

    handle = glossary.compile_glossary_catalog(
        [{"term": "Agent Clan", "definition": "A clan."}]
    )
    spans = glossary.scan_glossary_spans(handle, "see agent clan")
    lookup = glossary.lookup_glossary_span(
        handle, "see agent clan", line=0, character=5
    )

    assert spans[0].term == "Agent Clan"
    assert spans[0].byte_start == 4
    assert lookup == spans[0]


def test_glossary_facade_rehydrates_validation_diagnostics(monkeypatch) -> None:
    def fake_binding(name: str):
        assert name == "glossary_validate"
        return lambda entries: [
            {
                "severity": "error",
                "code": "alias_conflict",
                "message": "conflict",
                "path": "glossary.Agent.aliases[0]",
            }
        ]

    monkeypatch.setattr(glossary, "require_rust_binding", fake_binding)

    diagnostics = glossary.validate_glossary_entries(
        [{"term": "Agent", "definition": "An agent.", "aliases": ["worker"]}]
    )

    assert diagnostics[0].code == "alias_conflict"
    assert diagnostics[0].path == "glossary.Agent.aliases[0]"
