"""Shared app harness and catalog builders for Glossary panel tests."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console, RenderableType
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.glossary_panel_catalog import (
    GlossaryProjectRef,
    GlossaryProjectSnapshot,
)
from sase.ace.tui.modals import glossary_pane as glossary_pane_module
from sase.ace.tui.modals.glossary_pane import GlossaryPane
from sase.ace.tui.modals.glossary_panel_load import GlossaryPanelInitialLoad
from sase.core.glossary_facade import GlossaryCatalog, GlossaryEntry
from sase.xprompt.glossary_catalog import (
    EditorGlossaryCatalog,
    EditorGlossaryProject,
    _GlossaryConfigSignature,
)


class GlossaryPanelTestApp(App[None]):
    """Mount a reusable Glossary pane as the app's content widget."""

    def __init__(self, panel: GlossaryPane) -> None:
        super().__init__()
        self.panel = panel

    def compose(self) -> ComposeResult:
        yield self.panel


def _plain(renderable: RenderableType) -> str:
    console = Console(width=200, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def panel_static_text(panel: GlossaryPane, widget_id: str) -> str:
    return _plain(panel.query_one(f"#{widget_id}", Static).content)


def project_ref(
    key: str, display_name: str, *, has_glossary: bool = True
) -> GlossaryProjectRef:
    return GlossaryProjectRef(
        key=key, display_name=display_name, workspace_dir="", has_glossary=has_glossary
    )


def glossary_entry(
    index: int, term: str, *, definition: str = "", aliases: tuple[str, ...] = ()
) -> GlossaryEntry:
    return GlossaryEntry(
        index=index,
        term=term,
        normalized_term=term.casefold(),
        definition=definition or f"Definition of {term}.",
        configured_aliases=aliases,
        display_aliases=aliases,
        effective_aliases=(term.casefold(), *aliases),
        source={"config_path": f"/tmp/{term}/sase.yml"},
    )


class _CompiledGlossary:
    def scan(self, _text: str) -> list[dict[str, Any]]:
        return []


class _ScanningCompiledGlossary:
    """Substring-matches configured entries' terms, for outbound-chip tests."""

    def __init__(self, entries: tuple[GlossaryEntry, ...]) -> None:
        self._entries = entries

    def scan(self, text: str) -> list[dict[str, Any]]:
        spans: list[dict[str, Any]] = []
        for entry in self._entries:
            start = text.find(entry.term)
            if start == -1:
                continue
            spans.append(_span_at(entry.index, entry.term, start=start))
        return spans


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


def _catalog(
    ref: GlossaryProjectRef,
    entries: tuple[GlossaryEntry, ...],
    *,
    scanning: bool = False,
) -> EditorGlossaryCatalog:
    config_path = Path(f"/tmp/{ref.key}/sase.yml")
    return EditorGlossaryCatalog(
        schema_version=1,
        project=EditorGlossaryProject(
            key=ref.key, name=ref.display_name, aliases=(), workspace_dir=Path(".")
        ),
        config_path=config_path,
        config_signature=_GlossaryConfigSignature(
            path=str(config_path), mtime_ns=1, size=1
        ),
        catalog=GlossaryCatalog(schema_version=1, entries=entries),
        compiled=_ScanningCompiledGlossary(entries)
        if scanning
        else _CompiledGlossary(),
    )


def project_snapshot(
    ref: GlossaryProjectRef,
    entries: tuple[GlossaryEntry, ...] = (),
    *,
    diagnostics: tuple[str, ...] = (),
    reverse_references: dict[int, tuple[str, ...]] | None = None,
    scanning: bool = False,
) -> GlossaryProjectSnapshot:
    catalog = _catalog(ref, entries, scanning=scanning) if entries else None
    return GlossaryProjectSnapshot(
        project=ref,
        catalog=catalog,
        reverse_references=reverse_references or {},
        diagnostics=diagnostics,
    )


def install_fixed_load(
    monkeypatch: pytest.MonkeyPatch,
    ring: tuple[GlossaryProjectRef, ...],
    snapshots: dict[str, GlossaryProjectSnapshot],
    *,
    project_index: int = 0,
) -> list[bool]:
    """Patch the panel's off-thread loaders and record which thread called them."""
    off_main_thread: list[bool] = []

    def fake_initial_load(
        *,
        launch_workspace: str | None = None,
        initial_project_key: str | None = None,
        seed_from_current_project: bool = True,
        session_project_key: str | None = None,
    ) -> GlossaryPanelInitialLoad:
        del launch_workspace, seed_from_current_project
        off_main_thread.append(
            threading.current_thread() is not threading.main_thread()
        )
        index = project_index
        selected_key = initial_project_key or session_project_key
        if selected_key is not None:
            for i, candidate in enumerate(ring):
                if candidate.key == selected_key:
                    index = i
                    break
        if not ring:
            return GlossaryPanelInitialLoad(ring=(), project_index=0, snapshot=None)
        return GlossaryPanelInitialLoad(
            ring=ring, project_index=index, snapshot=snapshots[ring[index].key]
        )

    def fake_project_load(ref: GlossaryProjectRef) -> GlossaryProjectSnapshot:
        off_main_thread.append(
            threading.current_thread() is not threading.main_thread()
        )
        return snapshots[ref.key]

    monkeypatch.setattr(
        glossary_pane_module, "load_glossary_panel_initial_state", fake_initial_load
    )
    monkeypatch.setattr(
        glossary_pane_module, "load_glossary_project_snapshot", fake_project_load
    )
    return off_main_thread
