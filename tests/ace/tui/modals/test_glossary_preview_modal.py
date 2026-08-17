"""Behavior tests for the glossary preview modal."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.testing import wait_for
from sase.ace.tui.modals.glossary_preview_modal import GlossaryPreviewModal
from sase.core.glossary_facade import GlossaryCatalog, GlossaryEntry
from sase.xprompt.glossary_catalog import (
    EditorGlossaryCatalog,
    EditorGlossaryProject,
    _GlossaryConfigSignature,
)


class _GlossaryModalTestApp(App[None]):
    def __init__(self, modal: GlossaryPreviewModal) -> None:
        super().__init__()
        self.modal = modal

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(self.modal)


async def test_glossary_modal_follows_references_and_goes_back(
    tmp_path: Path,
) -> None:
    catalog, entries = _catalog(tmp_path)
    modal = GlossaryPreviewModal(catalog, entries[0], matched_text="hood")
    app = _GlossaryModalTestApp(modal)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert modal._entry is entries[0]
        assert "1-9 see also" in modal._build_footer()

        await pilot.press("1")
        await wait_for(pilot, lambda: modal._entry is entries[1])
        assert modal._matched_text is None
        assert "backspace" in modal._build_footer()

        await pilot.press("9")
        await pilot.pause()
        assert modal._entry is entries[1]

        await pilot.press("backspace")
        await wait_for(pilot, lambda: modal._entry is entries[0])

        await pilot.press("backspace")
        await pilot.pause()
        assert app.screen_stack[-1] is modal
        assert modal._entry is entries[0]


async def test_glossary_modal_source_actions_warn_without_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _entry(0, "Detached Term", definition="No source path.")
    catalog = SimpleNamespace(
        project=SimpleNamespace(name="sase", key="sase"),
        entries=(entry,),
        compiled=_CompiledGlossary((entry,)),
        config_path=None,
    )
    modal = GlossaryPreviewModal(catalog, entry, matched_text="Detached Term")
    app = _GlossaryModalTestApp(modal)
    notifications: list[tuple[str, str]] = []

    def notify(
        message: str,
        *,
        severity: str = "information",
        **_kwargs: Any,
    ) -> None:
        notifications.append((message, severity))

    monkeypatch.setattr(app, "notify", notify)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert "Y path" not in modal._build_footer()
        assert "o editor" not in modal._build_footer()
        assert "Z viewer" not in modal._build_footer()

        await pilot.press("Y")
        await pilot.press("o")
        await pilot.press("Z")
        await pilot.pause()

    assert notifications == [
        ("This preview does not have a path to copy", "warning"),
        ("This preview does not have a file to edit", "warning"),
        ("This preview does not have a file to view", "warning"),
    ]


def _catalog(
    tmp_path: Path,
) -> tuple[EditorGlossaryCatalog, tuple[GlossaryEntry, ...]]:
    config_path = tmp_path / "sase.yml"
    entries = (
        _entry(
            0,
            "Agent Hood",
            definition="An Agent Hood points at Sase Agent before Agent Clan.",
            config_path=config_path,
        ),
        _entry(
            1,
            "Sase Agent",
            definition="A lane is a sequential agent home.",
            config_path=config_path,
        ),
        _entry(
            2,
            "Agent Clan",
            definition="A clan is a collaborating group.",
            config_path=config_path,
        ),
    )
    return (
        EditorGlossaryCatalog(
            schema_version=1,
            project=EditorGlossaryProject(
                key="sase",
                name="sase",
                aliases=(),
                workspace_dir=tmp_path,
            ),
            config_path=config_path,
            config_signature=_GlossaryConfigSignature(
                path=str(config_path),
                mtime_ns=1,
                size=256,
            ),
            catalog=GlossaryCatalog(schema_version=1, entries=entries),
            compiled=_CompiledGlossary(entries),
        ),
        entries,
    )


def _entry(
    index: int,
    term: str,
    *,
    definition: str,
    config_path: Path | None = None,
) -> GlossaryEntry:
    source = None
    if config_path is not None:
        source = {
            "config_path": str(config_path),
            "definition_range": {
                "start": {"line": index + 1, "character": 4},
                "end": {"line": index + 1, "character": 40},
            },
        }
    return GlossaryEntry(
        index=index,
        term=term,
        normalized_term=term.casefold(),
        definition=definition,
        configured_aliases=(),
        display_aliases=(),
        effective_aliases=(term.casefold(),),
        source=source,
    )


class _CompiledGlossary:
    def __init__(self, entries: tuple[GlossaryEntry, ...]) -> None:
        self._entries = entries

    def scan(self, text: str) -> list[dict[str, Any]]:
        spans: list[tuple[int, dict[str, Any]]] = []
        for entry in self._entries:
            start = 0
            while True:
                found = text.find(entry.term, start)
                if found == -1:
                    break
                end = found + len(entry.term)
                spans.append((found, _span(entry, text[found:end], found, end)))
                start = end
        return [span for _found, span in sorted(spans, key=lambda item: item[0])]


def _span(
    entry: GlossaryEntry,
    matched_text: str,
    start: int,
    end: int,
) -> dict[str, Any]:
    return {
        "term": entry.term,
        "entry_index": entry.index,
        "alias_index": 0,
        "alias": entry.term,
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
