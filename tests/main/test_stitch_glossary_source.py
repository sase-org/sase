"""Packaged Stitch glossary names the canonical tracked VCS command."""

from __future__ import annotations

from pathlib import Path

from sase.memory.web.catalog import find_memory_web, memory_web_glossary_entries

ROOT = Path(__file__).resolve().parents[2]


def test_stitch_glossary_identifies_stitch_create() -> None:
    web = find_memory_web(ROOT, "glossary")
    assert web is not None
    definitions = {
        entry.term: entry.definition for entry in memory_web_glossary_entries(web)
    }

    definition = definitions["Stitch"]
    assert "sase stitch create" in definition
    assert "sase commit" not in definition
