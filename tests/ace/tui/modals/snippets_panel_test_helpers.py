"""Shared app harness and catalog builders for Snippets panel tests."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from rich.console import Console, RenderableType
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals import snippets_panel as snippets_panel_module
from sase.ace.tui.modals.snippets_panel import SnippetsPane, SnippetsPanel
from sase.ace.tui.modals.snippets_panel_load import SnippetsPanelInitialLoad
from sase.ace.tui.snippets_panel_catalog import (
    SnippetDestination,
    SnippetProjectRef,
    SnippetProjectSnapshot,
)
from sase.core.snippet_catalog_facade import (
    ComposedSnippetCatalog,
    SnippetCall,
    SnippetSourceSpan,
)
from sase.snippet.models import (
    SnippetCatalog,
    SnippetCatalogContext,
    SnippetEntry,
    SnippetRelations,
    SnippetSourceContribution,
    SnippetSourceKind,
)


type SnippetsPanelSubject = SnippetsPane | SnippetsPanel


class SnippetsPanelTestApp(App[None]):
    def __init__(self, panel: SnippetsPanel) -> None:
        super().__init__()
        self.panel = panel

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(self.panel)


class SnippetsPaneTestApp(App[None]):
    def __init__(self, pane: SnippetsPane) -> None:
        super().__init__()
        self.pane = pane

    def compose(self) -> ComposeResult:
        yield self.pane


def _plain(renderable: RenderableType) -> str:
    console = Console(width=200, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def panel_static_text(panel: SnippetsPanelSubject, widget_id: str) -> str:
    return _plain(panel.query_one(f"#{widget_id}", Static).content)


def project_ref(key: str, display_name: str) -> SnippetProjectRef:
    return SnippetProjectRef(key=key, display_name=display_name, workspace_dir="")


def snippet_call(
    target: str,
    *,
    status: str = "resolved",
    start: int = 0,
    end: int = 0,
    canonical: str | None = None,
) -> SnippetCall:
    return SnippetCall(
        authored_target=target,
        canonical_target=canonical
        if canonical is not None
        else (target if status == "resolved" else None),
        positional_args=(),
        span=SnippetSourceSpan(start=start, end=end or start),
        status=status,  # type: ignore[arg-type]
    )


def snippet_entry(
    trigger: str,
    *,
    raw: str | None = None,
    composed: str | None = None,
    kind: SnippetSourceKind = "project",
    path: str | None = "/tmp/sase.yml",
    writable: bool = True,
    aliases: tuple[str, ...] = (),
    outbound: tuple[str, ...] = (),
    inbound: tuple[str, ...] = (),
    calls: tuple[SnippetCall, ...] = (),
    xprompt_name: str | None = None,
    contributions: tuple[SnippetSourceContribution, ...] | None = None,
) -> SnippetEntry:
    template = raw if raw is not None else f"{trigger}$0"
    origin = SnippetSourceContribution(
        trigger=trigger,
        template=template,
        kind=kind,
        path=path,
        display_path=path,
        writable=writable,
        xprompt_name=xprompt_name,
    )
    return SnippetEntry(
        trigger=trigger,
        raw_template=template,
        composed_template=composed if composed is not None else template,
        origin=origin,
        aliases=aliases,
        contributions=contributions or (origin,),
        relations=SnippetRelations(outbound=outbound, inbound=inbound, calls=calls),
        diagnostics=(),
    )


def _composed(entries: tuple[SnippetEntry, ...]) -> ComposedSnippetCatalog:
    return ComposedSnippetCatalog(
        templates={entry.trigger: entry.composed_template for entry in entries},
        alias_provenance={
            alias: entry.trigger for entry in entries for alias in entry.aliases
        },
        triggers={},
        calls={entry.trigger: entry.relations.calls for entry in entries},
        outbound={entry.trigger: entry.relations.outbound for entry in entries},
        inbound={entry.trigger: entry.relations.inbound for entry in entries},
        diagnostics=(),
    )


def _catalog(
    ref: SnippetProjectRef, entries: tuple[SnippetEntry, ...]
) -> SnippetCatalog:
    return SnippetCatalog(
        context=SnippetCatalogContext(
            key=ref.key,
            name=ref.display_name,
            aliases=(),
            workspace_dir=Path("."),
        ),
        entries=entries,
        composed=_composed(entries),
        layer_diagnostics=(),
        explicit_templates={entry.trigger: entry.raw_template for entry in entries},
        effective_config_templates={},
    )


def project_snapshot(
    ref: SnippetProjectRef,
    entries: tuple[SnippetEntry, ...] = (),
    *,
    diagnostics: tuple[str, ...] = (),
    catalog: SnippetCatalog | None | object = ...,
    destinations: tuple[SnippetDestination, ...] = (),
    default_destination_path: str | None = None,
) -> SnippetProjectSnapshot:
    resolved: SnippetCatalog | None
    if catalog is ...:
        resolved = _catalog(ref, entries) if entries else None
    else:
        resolved = catalog  # type: ignore[assignment]
    return SnippetProjectSnapshot(
        project=ref,
        catalog=resolved,
        diagnostics=diagnostics,
        destinations=destinations,
        default_destination_path=default_destination_path,
    )


def install_fixed_load(
    monkeypatch: pytest.MonkeyPatch,
    ring: tuple[SnippetProjectRef, ...],
    snapshots: dict[str, SnippetProjectSnapshot],
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
    ) -> SnippetsPanelInitialLoad:
        off_main_thread.append(
            threading.current_thread() is not threading.main_thread()
        )
        index = project_index
        if initial_project_key is not None:
            for i, candidate in enumerate(ring):
                if candidate.key == initial_project_key:
                    index = i
                    break
        if not ring:
            return SnippetsPanelInitialLoad(ring=(), project_index=0, snapshot=None)
        return SnippetsPanelInitialLoad(
            ring=ring, project_index=index, snapshot=snapshots[ring[index].key]
        )

    def fake_project_load(ref: SnippetProjectRef) -> SnippetProjectSnapshot:
        off_main_thread.append(
            threading.current_thread() is not threading.main_thread()
        )
        return snapshots[ref.key]

    monkeypatch.setattr(
        snippets_panel_module,
        "load_snippets_panel_initial_state",
        fake_initial_load,
    )
    monkeypatch.setattr(
        snippets_panel_module, "load_snippet_project_snapshot", fake_project_load
    )
    return off_main_thread
