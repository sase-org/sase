"""Shared test helpers for prompt repo-mention behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.repo_inventory import RepoRecord
from sase.xprompt.glossary_catalog import EditorGlossaryProject
from sase.xprompt.repo_mention_catalog import EditorRepoMentionCatalog, RepoMention


def install_warm_repo_mentions(
    monkeypatch: pytest.MonkeyPatch,
    app: Any,
    catalog: EditorRepoMentionCatalog,
) -> None:
    monkeypatch.setattr(
        app,
        "get_prompt_repo_mention_catalog",
        lambda _context, *, schedule=True: catalog,
        raising=False,
    )
    monkeypatch.setattr(
        app,
        "is_prompt_repo_mention_catalog_warm",
        lambda _context: True,
        raising=False,
    )
    monkeypatch.setattr(
        app,
        "warm_prompt_repo_mention_catalog",
        lambda _context: None,
        raising=False,
    )


class _FakeCompiledRepoMentions:
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


class _DynamicCompiledRepoMentions:
    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
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
            _span_wire(text, self.identifier, start, start + len(self.identifier))
            for start in _all_occurrence_offsets(text, self.identifier)
        )


def catalog_for_text(
    text: str,
    tmp_path: Path,
    identifier: str,
    *,
    occurrence_count: int = 1,
) -> EditorRepoMentionCatalog:
    spans = tuple(
        _span_wire(text, identifier, start, start + len(identifier))
        for start in _occurrence_offsets(text, identifier, occurrence_count)
    )
    return _catalog(tmp_path, identifier, _FakeCompiledRepoMentions(spans))


def dynamic_catalog_for_identifier(
    tmp_path: Path,
    identifier: str,
    *,
    project_key: str = "sase",
    project_name: str = "sase",
) -> EditorRepoMentionCatalog:
    return _catalog(
        tmp_path,
        identifier,
        _DynamicCompiledRepoMentions(identifier),
        project_key=project_key,
        project_name=project_name,
    )


def _catalog(
    tmp_path: Path,
    identifier: str,
    compiled: object,
    *,
    project_key: str = "sase",
    project_name: str = "sase",
) -> EditorRepoMentionCatalog:
    config_path = tmp_path / f"{project_key}.yml"
    record = RepoRecord(
        name=identifier,
        kind="linked",
        project=project_name,
        project_key=project_key,
        path=str(tmp_path / identifier),
        exists=True,
        auto_clone=False,
        description="Shared Rust core backend.",
        source="test",
        env_name=None,
        slug=None,
    )
    mention = RepoMention(
        identifier=identifier,
        kind="linked",
        record=record,
        index=0,
        config_path=str(config_path),
        config_line=16,
        config_col=7,
    )
    return EditorRepoMentionCatalog(
        schema_version=1,
        project=EditorGlossaryProject(
            key=project_key,
            name=project_name,
            aliases=(),
            workspace_dir=tmp_path,
        ),
        mentions=(mention,),
        compiled=compiled,
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


def _span_wire(text: str, identifier: str, start: int, end: int) -> dict[str, Any]:
    return {
        "term": identifier,
        "entry_index": 0,
        "alias_index": 0,
        "alias": identifier,
        "matched_text": text[start:end],
        "byte_start": len(text[:start].encode("utf-8")),
        "byte_end": len(text[:end].encode("utf-8")),
        "range": _editor_range(text, start, end),
        "segments": [
            {
                "byte_start": len(text[:start].encode("utf-8")),
                "byte_end": len(text[:end].encode("utf-8")),
                "range": _editor_range(text, start, end),
            }
        ],
    }


def _editor_range(text: str, start: int, end: int) -> dict[str, Any]:
    return {
        "start": _editor_position(text, start),
        "end": _editor_position(text, end),
    }


def _editor_position(text: str, offset: int) -> dict[str, Any]:
    prefix = text[:offset]
    line = prefix.count("\n")
    line_start = prefix.rfind("\n") + 1
    return {
        "line": line,
        "character": _utf16_character(text[line_start:offset]),
    }


def _utf16_character(text: str) -> int:
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)
