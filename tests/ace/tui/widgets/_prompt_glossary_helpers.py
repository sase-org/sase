"""Shared test helpers for prompt glossary behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.core.glossary_facade import GlossaryCatalog, GlossaryEntry
from sase.xprompt.glossary_catalog import (
    EditorGlossaryCatalog,
    EditorGlossaryProject,
    _GlossaryConfigSignature,
)


def install_warm_glossary(
    monkeypatch: pytest.MonkeyPatch,
    app: Any,
    catalog: EditorGlossaryCatalog,
) -> None:
    monkeypatch.setattr(
        app,
        "get_prompt_glossary_catalog",
        lambda _context, *, schedule=True: catalog,
        raising=False,
    )
    monkeypatch.setattr(
        app,
        "is_prompt_glossary_catalog_warm",
        lambda _context: True,
        raising=False,
    )
    monkeypatch.setattr(
        app,
        "warm_prompt_glossary_catalog",
        lambda _context: None,
        raising=False,
    )


class _FakeCompiledGlossary:
    def __init__(self, spans: tuple[dict[str, Any], ...]) -> None:
        self._spans = spans

    def scan(self, _text: str) -> list[dict[str, Any]]:
        return list(self._spans)

    def lookup(
        self,
        _text: str,
        line: int,
        character: int,
    ) -> dict[str, Any] | None:
        for span in self._spans:
            editor_range = span["range"]
            start = editor_range["start"]
            end = editor_range["end"]
            if (
                start["line"] <= line <= end["line"]
                and (line > start["line"] or character >= start["character"])
                and (line < end["line"] or character < end["character"])
            ):
                return span
        return None


class _DynamicCompiledGlossary:
    def __init__(self, term: str) -> None:
        self.term = term
        self.scan_calls = 0

    def scan(self, text: str) -> list[dict[str, Any]]:
        self.scan_calls += 1
        return list(self._spans_for_text(text))

    def lookup(
        self,
        text: str,
        line: int,
        character: int,
    ) -> dict[str, Any] | None:
        for span in self._spans_for_text(text):
            editor_range = span["range"]
            start = editor_range["start"]
            end = editor_range["end"]
            if (
                start["line"] <= line <= end["line"]
                and (line > start["line"] or character >= start["character"])
                and (line < end["line"] or character < end["character"])
            ):
                return span
        return None

    def _spans_for_text(self, text: str) -> tuple[dict[str, Any], ...]:
        return tuple(
            _span_wire(text, self.term, start, start + len(self.term))
            for start in _all_occurrence_offsets(text, self.term)
        )


def catalog_for_text(
    text: str,
    tmp_path: Path,
    term: str,
    *,
    entry_term: str | None = None,
    occurrence_count: int = 1,
) -> EditorGlossaryCatalog:
    entry_term = entry_term or term
    spans = tuple(
        _span_wire(text, term, start, start + len(term))
        for start in _occurrence_offsets(text, term, occurrence_count)
    )
    config_path = tmp_path / "sase.yml"
    entry = GlossaryEntry(
        index=0,
        term=entry_term,
        normalized_term=entry_term.casefold(),
        definition="A named, rootless container for coordinated agents.",
        configured_aliases=("clan", "agent clans"),
        display_aliases=("clan",),
        effective_aliases=("agent clan", "clan", "agent clans"),
        source={
            "config_path": str(config_path),
            "definition_range": {
                "start": {"line": 7, "character": 4},
                "end": {"line": 7, "character": 58},
            },
        },
    )
    return EditorGlossaryCatalog(
        schema_version=1,
        project=EditorGlossaryProject(
            key="sase",
            name="sase",
            aliases=("sase-org",),
            workspace_dir=tmp_path,
        ),
        config_path=config_path,
        config_signature=_GlossaryConfigSignature(
            path=str(config_path),
            mtime_ns=1,
            size=256,
        ),
        catalog=GlossaryCatalog(schema_version=1, entries=(entry,)),
        compiled=_FakeCompiledGlossary(spans),
    )


def catalog_for_wrapped_text(
    text: str,
    tmp_path: Path,
    term: str,
    *,
    entry_term: str | None = None,
) -> EditorGlossaryCatalog:
    parts = term.split()
    assert len(parts) == 2
    first, second = parts
    start = text.find(first)
    assert start != -1
    second_start = text.find(second, start + len(first))
    assert second_start != -1
    end = second_start + len(second)
    entry_term = entry_term or term
    span = _span_wire(
        text,
        term,
        start,
        end,
        segments=((start, start + len(first)), (second_start, end)),
    )
    config_path = tmp_path / "sase.yml"
    entry = GlossaryEntry(
        index=0,
        term=entry_term,
        normalized_term=entry_term.casefold(),
        definition="A named, rootless container for coordinated agents.",
        configured_aliases=("clan", "agent clans"),
        display_aliases=("clan",),
        effective_aliases=("agent clan", "clan", "agent clans"),
        source={
            "config_path": str(config_path),
            "definition_range": {
                "start": {"line": 7, "character": 4},
                "end": {"line": 7, "character": 58},
            },
        },
    )
    return EditorGlossaryCatalog(
        schema_version=1,
        project=EditorGlossaryProject(
            key="sase",
            name="sase",
            aliases=("sase-org",),
            workspace_dir=tmp_path,
        ),
        config_path=config_path,
        config_signature=_GlossaryConfigSignature(
            path=str(config_path),
            mtime_ns=1,
            size=256,
        ),
        catalog=GlossaryCatalog(schema_version=1, entries=(entry,)),
        compiled=_FakeCompiledGlossary((span,)),
    )


def dynamic_catalog_for_term(
    tmp_path: Path,
    term: str,
    *,
    project_key: str = "sase",
    project_name: str = "sase",
) -> EditorGlossaryCatalog:
    config_path = tmp_path / f"{project_key}.yml"
    entry = GlossaryEntry(
        index=0,
        term=term,
        normalized_term=term.casefold(),
        definition="A named, rootless container for coordinated agents.",
        configured_aliases=("clan", "agent clans"),
        display_aliases=("clan",),
        effective_aliases=(term.casefold(), "clan", "agent clans"),
        source={
            "config_path": str(config_path),
            "definition_range": {
                "start": {"line": 7, "character": 4},
                "end": {"line": 7, "character": 58},
            },
        },
    )
    return EditorGlossaryCatalog(
        schema_version=1,
        project=EditorGlossaryProject(
            key=project_key,
            name=project_name,
            aliases=(),
            workspace_dir=tmp_path,
        ),
        config_path=config_path,
        config_signature=_GlossaryConfigSignature(
            path=str(config_path),
            mtime_ns=1,
            size=256,
        ),
        catalog=GlossaryCatalog(schema_version=1, entries=(entry,)),
        compiled=_DynamicCompiledGlossary(term),
    )


def _occurrence_offsets(text: str, term: str, count: int) -> tuple[int, ...]:
    offsets: list[int] = []
    start = 0
    while len(offsets) < count:
        found = text.find(term, start)
        assert found != -1
        offsets.append(found)
        start = found + len(term)
    return tuple(offsets)


def _all_occurrence_offsets(text: str, term: str) -> tuple[int, ...]:
    offsets: list[int] = []
    start = 0
    while True:
        found = text.find(term, start)
        if found == -1:
            return tuple(offsets)
        offsets.append(found)
        start = found + len(term)


def _span_wire(
    text: str,
    term: str,
    start: int,
    end: int,
    *,
    segments: tuple[tuple[int, int], ...] | None = None,
) -> dict[str, Any]:
    segment_offsets = segments or ((start, end),)
    return {
        "term": term,
        "entry_index": 0,
        "alias_index": 0,
        "alias": term,
        "matched_text": text[start:end],
        "byte_start": len(text[:start].encode("utf-8")),
        "byte_end": len(text[:end].encode("utf-8")),
        "range": _editor_range(text, start, end),
        "segments": [
            {
                "byte_start": len(text[:segment_start].encode("utf-8")),
                "byte_end": len(text[:segment_end].encode("utf-8")),
                "range": _editor_range(text, segment_start, segment_end),
            }
            for segment_start, segment_end in segment_offsets
        ],
    }


def _editor_range(text: str, start: int, end: int) -> dict[str, Any]:
    return {
        "start": _editor_position(text, start),
        "end": _editor_position(text, end),
    }


def _editor_position(text: str, offset: int) -> dict[str, int]:
    prefix = text[:offset]
    line = prefix.count("\n")
    line_start = prefix.rfind("\n") + 1
    return {
        "line": line,
        "character": _utf16_character(text[line_start:offset]),
    }


def _utf16_character(text: str) -> int:
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)
