"""Behavior tests for the Glossary panel shell."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console, RenderableType
from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static

from sase.ace.testing import wait_for
from sase.ace.tui.glossary_panel_catalog import (
    GlossaryProjectRef,
    GlossaryProjectSnapshot,
)
from sase.ace.tui.modals import glossary_panel as glossary_panel_module
from sase.ace.tui.modals.glossary_panel import GlossaryPanel
from sase.ace.tui.modals.glossary_panel_load import GlossaryPanelInitialLoad
from sase.core.glossary_facade import GlossaryCatalog, GlossaryEntry
from sase.xprompt.glossary_catalog import (
    EditorGlossaryCatalog,
    EditorGlossaryProject,
    _GlossaryConfigSignature,
)


class _GlossaryPanelTestApp(App[None]):
    def __init__(self, panel: GlossaryPanel) -> None:
        super().__init__()
        self.panel = panel

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(self.panel)


def _plain(renderable: RenderableType) -> str:
    console = Console(width=200, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def _static_text(panel: GlossaryPanel, widget_id: str) -> str:
    return _plain(panel.query_one(f"#{widget_id}", Static).content)


def _ref(
    key: str, display_name: str, *, has_glossary: bool = True
) -> GlossaryProjectRef:
    return GlossaryProjectRef(
        key=key, display_name=display_name, workspace_dir="", has_glossary=has_glossary
    )


def _entry(
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


def _catalog(
    ref: GlossaryProjectRef, entries: tuple[GlossaryEntry, ...]
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
        compiled=_CompiledGlossary(),
    )


def _snapshot(
    ref: GlossaryProjectRef,
    entries: tuple[GlossaryEntry, ...] = (),
    *,
    diagnostics: tuple[str, ...] = (),
) -> GlossaryProjectSnapshot:
    catalog = _catalog(ref, entries) if entries else None
    return GlossaryProjectSnapshot(
        project=ref, catalog=catalog, reverse_references={}, diagnostics=diagnostics
    )


def _install_fixed_load(
    monkeypatch: pytest.MonkeyPatch,
    ring: tuple[GlossaryProjectRef, ...],
    snapshots: dict[str, GlossaryProjectSnapshot],
    *,
    project_index: int = 0,
) -> list[bool]:
    """Patch the panel's off-thread loaders and record which thread called them."""
    off_main_thread: list[bool] = []

    def fake_initial_load(
        *, launch_workspace: str | None = None, initial_project_key: str | None = None
    ) -> GlossaryPanelInitialLoad:
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
        glossary_panel_module, "load_glossary_panel_initial_state", fake_initial_load
    )
    monkeypatch.setattr(
        glossary_panel_module, "load_glossary_project_snapshot", fake_project_load
    )
    return off_main_thread


async def test_panel_mounts_and_selects_first_term(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    entries = (_entry(0, "Zebra"), _entry(1, "Agent Hood"), _entry(2, "Middle"))
    off_main_thread = _install_fixed_load(
        monkeypatch, (ref,), {"sase": _snapshot(ref, entries)}
    )

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_term == "Agent Hood"
        assert [entry.term for entry in panel._entries] == [
            "Agent Hood",
            "Middle",
            "Zebra",
        ]
        assert off_main_thread == [True]
        assert "Agent Hood" in _static_text(panel, "glossary-panel-card-title")


async def test_next_term_updates_card_after_debounce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    entries = (_entry(0, "Agent Hood"), _entry(1, "Zebra"))
    _install_fixed_load(monkeypatch, (ref,), {"sase": _snapshot(ref, entries)})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("j")
        await wait_for(pilot, lambda: panel._current_term == "Zebra")

        def _title_shows_zebra() -> bool:
            return "Zebra" in _static_text(panel, "glossary-panel-card-title")

        await wait_for(pilot, _title_shows_zebra, timeout=2.0)


async def test_filter_matches_terms_aliases_and_definitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    entries = (
        _entry(0, "Agent Hood", aliases=("hood",)),
        _entry(1, "Sase Agent", definition="Mentions hood in passing."),
        _entry(2, "Zebra"),
    )
    _install_fixed_load(monkeypatch, (ref,), {"sase": _snapshot(ref, entries)})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)

        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "hood":
            await pilot.press(char)
        await wait_for(
            pilot, lambda: [e.term for e in panel._entries] == ["Agent Hood"]
        )

        # Toggling definition matching (from the term list, not the filter box)
        # widens the same pattern to also match "Sase Agent"'s definition.
        await pilot.press("escape")
        await wait_for(pilot, lambda: not panel._filter_input().display)
        await pilot.press("full_stop")
        await wait_for(
            pilot,
            lambda: (
                sorted(e.term for e in panel._entries) == ["Agent Hood", "Sase Agent"]
            ),
        )


async def test_empty_filter_shows_no_match_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    entries = (_entry(0, "Agent Hood"),)
    _install_fixed_load(monkeypatch, (ref,), {"sase": _snapshot(ref, entries)})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "nomatch":
            await pilot.press(char)
        await wait_for(pilot, lambda: not panel._entries)
        assert "no terms matched: nomatch" in _static_text(
            panel, "glossary-panel-card-meta"
        )


async def test_project_cycling_orders_by_display_name_and_scopes_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = _ref("proj-a", "Alpha")
    ref_b = _ref("proj-b", "Beta")
    snapshots = {
        "proj-a": _snapshot(ref_a, (_entry(0, "Only In Alpha"),)),
        "proj-b": _snapshot(ref_b, (_entry(0, "Only In Beta"),)),
    }
    _install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._project_index == 0
        assert [e.term for e in panel._entries] == ["Only In Alpha"]

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 1)
        assert [e.term for e in panel._entries] == ["Only In Beta"]

        await pilot.press("P")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 0)
        assert [e.term for e in panel._entries] == ["Only In Alpha"]


async def test_no_glossary_project_shows_invitation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase", has_glossary=False)
    _install_fixed_load(monkeypatch, (ref,), {"sase": _snapshot(ref, ())})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        meta = _static_text(panel, "glossary-panel-card-meta")
        assert "no glossary terms yet" in meta
        assert "sase" in meta


async def test_diagnostics_project_shows_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    snapshot = _snapshot(ref, (), diagnostics=("sase.yml: bad glossary shape",))
    _install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert "bad glossary shape" in _static_text(panel, "glossary-panel-card-meta")


async def test_initial_and_project_switch_loads_run_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = _ref("proj-a", "Alpha")
    ref_b = _ref("proj-b", "Beta")
    snapshots = {
        "proj-a": _snapshot(ref_a, (_entry(0, "A"),)),
        "proj-b": _snapshot(ref_b, (_entry(0, "B"),)),
    }
    off_main_thread = _install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 1)

    assert off_main_thread == [True, True]


async def test_term_list_option_list_widget_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    entries = (_entry(0, "Agent Hood"),)
    _install_fixed_load(monkeypatch, (ref,), {"sase": _snapshot(ref, entries)})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        option_list = panel.query_one("#glossary-panel-terms", OptionList)
        assert option_list.option_count == 1
