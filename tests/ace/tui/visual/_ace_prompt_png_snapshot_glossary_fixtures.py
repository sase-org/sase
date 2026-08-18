"""Deterministic glossary catalog fixtures for ACE prompt PNG snapshots."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui import AceApp
from sase.ace.tui.glossary_catalog import PromptGlossaryContext
from sase.core.glossary_facade import GlossaryCatalog, GlossaryEntry
from sase.xprompt.glossary_catalog import (
    EditorGlossaryCatalog,
    EditorGlossaryProject,
    _GlossaryConfigSignature,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_wire import (
    VisualCompiledSpans,
    visual_editor_range,
    visual_literal_ranges,
    visual_span_segment,
)


def patch_visual_glossary_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _visual_glossary_catalog()

    def _catalog(
        _app: AceApp,
        _context: PromptGlossaryContext,
        *,
        schedule: bool = True,
    ) -> EditorGlossaryCatalog:
        del schedule
        return catalog

    def _warm(
        _app: AceApp,
        _context: PromptGlossaryContext,
    ) -> None:
        return None

    monkeypatch.setattr(AceApp, "get_prompt_glossary_catalog", _catalog)
    monkeypatch.setattr(
        AceApp,
        "is_prompt_glossary_catalog_warm",
        lambda _app, _context: True,
    )
    monkeypatch.setattr(AceApp, "warm_prompt_glossary_catalog", _warm)


class _VisualCompiledGlossary(VisualCompiledSpans):
    def __init__(self, entries: tuple[GlossaryEntry, ...]) -> None:
        self._entries = entries

    def scan(self, text: str) -> list[dict[str, Any]]:
        literal_ranges = visual_literal_ranges(text)
        spans: list[dict[str, Any]] = []
        for entry in self._entries:
            pattern = _visual_glossary_pattern(entry.term)
            literal_index = 0
            for match in pattern.finditer(text):
                found = match.start()
                end = match.end()
                while (
                    literal_index < len(literal_ranges)
                    and literal_ranges[literal_index][1] <= found
                ):
                    literal_index += 1
                if (
                    literal_index < len(literal_ranges)
                    and literal_ranges[literal_index][0] < end
                ):
                    continue
                spans.append(
                    _visual_glossary_span_wire(
                        text,
                        entry,
                        found,
                        end,
                    )
                )
        return spans


def _visual_glossary_catalog() -> EditorGlossaryCatalog:
    config_path = Path("/workspace/sase/sase.yml")
    entries = (
        _visual_glossary_entry(
            index=0,
            term="Agent Clan",
            definition="Named group of collaborating agents.",
            config_path=config_path,
            line=8,
        ),
        _visual_glossary_entry(
            index=1,
            term="Patch",
            definition="SASE local unit of change for PR work.",
            config_path=config_path,
            line=16,
        ),
        _visual_glossary_entry(
            index=2,
            term="xprompt",
            definition="Prompt shortcut expanded by SASE.",
            config_path=config_path,
            line=24,
        ),
    )
    return EditorGlossaryCatalog(
        schema_version=1,
        project=EditorGlossaryProject(
            key="sase",
            name="sase",
            aliases=("sase-org",),
            workspace_dir=Path("/workspace/sase"),
        ),
        config_path=config_path,
        config_signature=_GlossaryConfigSignature(
            path=str(config_path),
            mtime_ns=1,
            size=2048,
        ),
        catalog=GlossaryCatalog(schema_version=1, entries=entries),
        compiled=_VisualCompiledGlossary(entries),
    )


def _visual_glossary_entry(
    *,
    index: int,
    term: str,
    definition: str,
    config_path: Path,
    line: int,
) -> GlossaryEntry:
    return GlossaryEntry(
        index=index,
        term=term,
        normalized_term=term.casefold(),
        definition=definition,
        configured_aliases=(),
        display_aliases=(),
        effective_aliases=(term.casefold(),),
        source={
            "config_path": str(config_path),
            "definition_range": {
                "start": {"line": line, "character": 4},
                "end": {"line": line, "character": 40},
            },
        },
    )


def _visual_glossary_span_wire(
    text: str,
    entry: GlossaryEntry,
    start: int,
    end: int,
) -> dict[str, Any]:
    return {
        "term": entry.term,
        "entry_index": entry.index,
        "alias_index": 0,
        "alias": entry.term,
        "matched_text": text[start:end],
        "byte_start": len(text[:start].encode("utf-8")),
        "byte_end": len(text[:end].encode("utf-8")),
        "range": visual_editor_range(text, start, end),
        "segments": _visual_glossary_segments(text, start, end),
    }


def _visual_glossary_pattern(term: str) -> re.Pattern[str]:
    gap = r"(?:[\t ]*\r?\n[\t ]*|[\t ]+)"
    words = [word for word in term.split() if word]
    return re.compile(
        r"\b" + gap.join(re.escape(word) for word in words) + r"\b",
        re.IGNORECASE,
    )


def _visual_glossary_segments(
    text: str,
    start: int,
    end: int,
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    cursor = start
    while cursor < end:
        newline = text.find("\n", cursor, end)
        piece_end = end if newline == -1 else newline
        segment_start = cursor
        segment_end = piece_end
        while segment_start < segment_end and text[segment_start] in " \t\r":
            segment_start += 1
        while segment_end > segment_start and text[segment_end - 1] in " \t\r":
            segment_end -= 1
        if segment_start < segment_end:
            segments.append(visual_span_segment(text, segment_start, segment_end))
        if newline == -1:
            break
        cursor = newline + 1
    return segments
