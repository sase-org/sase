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


def _snapshot(
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
        assert "No glossary in" in meta
        assert "sase" in meta
        assert "add the first term" in meta


async def test_no_glossary_invitation_uses_display_name_not_spec_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("gh_org__research", "Research", has_glossary=False)
    _install_fixed_load(monkeypatch, (ref,), {"gh_org__research": _snapshot(ref, ())})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        meta = _static_text(panel, "glossary-panel-card-meta")
        assert "Research" in meta
        assert "gh_org__research" not in meta


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


# --- travel: relation chips, digit shortcuts, and the back trail ----------


async def test_relation_chip_numbering_is_continuous_across_both_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    entries = (
        _entry(0, "Alpha", definition="Alpha mentions Beta and Gamma."),
        _entry(1, "Beta"),
        _entry(2, "Gamma"),
        _entry(3, "Delta"),
    )
    snapshot = _snapshot(
        ref, entries, reverse_references={0: ("Delta",)}, scanning=True
    )
    _install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_term == "Alpha"
        assert [entry.term for entry in panel._chip_entries] == [
            "Beta",
            "Gamma",
            "Delta",
        ]
        assert panel._chip_outbound_count == 2

        meta = _static_text(panel, "glossary-panel-card-meta")
        assert "SEE ALSO" in meta
        assert "REFERENCED BY" in meta
        assert "1 Beta" in meta
        assert "2 Gamma" in meta
        assert "3 Delta" in meta


async def test_digit_follows_referenced_by_chip_when_see_also_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    entries = (_entry(0, "AAA Leaf"), _entry(1, "BBB Ref"), _entry(2, "CCC Ref"))
    snapshot = _snapshot(ref, entries, reverse_references={0: ("BBB Ref", "CCC Ref")})
    _install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_term == "AAA Leaf"
        assert panel._chip_outbound_count == 0
        assert [entry.term for entry in panel._chip_entries] == [
            "BBB Ref",
            "CCC Ref",
        ]

        await pilot.press("2")
        await wait_for(pilot, lambda: panel._current_term == "CCC Ref")
        assert panel._trail == ["AAA Leaf"]


async def test_tab_moves_chip_cursor_and_wraps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    entries = (_entry(0, "Leaf"), _entry(1, "X"), _entry(2, "Y"))
    snapshot = _snapshot(ref, entries, reverse_references={0: ("X", "Y")})
    _install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._chip_cursor is None

        await pilot.press("tab")
        assert panel._chip_cursor == 0
        await pilot.press("tab")
        assert panel._chip_cursor == 1
        await pilot.press("tab")
        assert panel._chip_cursor == 0


async def test_follow_moves_term_cursor_and_pushes_trail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    entries = (_entry(0, "Leaf"), _entry(1, "X"), _entry(2, "Y"))
    snapshot = _snapshot(ref, entries, reverse_references={0: ("X", "Y")})
    _install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("tab")
        assert panel._chip_cursor == 0
        await pilot.press("l")
        await wait_for(pilot, lambda: panel._current_term == "X")
        assert panel._trail == ["Leaf"]
        assert panel._chip_cursor is None


async def test_follow_through_active_filter_clears_it_and_lands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    entries = (_entry(0, "Leaf"), _entry(1, "X"), _entry(2, "Y"))
    snapshot = _snapshot(ref, entries, reverse_references={0: ("X",)})
    _install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "leaf":
            await pilot.press(char)
        await wait_for(pilot, lambda: [e.term for e in panel._entries] == ["Leaf"])

        await pilot.press("escape")
        await wait_for(pilot, lambda: not panel._filter_input().display)

        await pilot.press("l")
        await wait_for(pilot, lambda: panel._current_term == "X")
        assert panel._filter_text == ""
        assert [e.term for e in panel._entries] == ["Leaf", "X", "Y"]


async def test_back_restores_previous_term_and_pops_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    entries = (_entry(0, "A"), _entry(1, "B"), _entry(2, "C"))
    snapshot = _snapshot(ref, entries, reverse_references={0: ("B",), 1: ("C",)})
    _install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_term == "A"

        panel._travel_forward("B")
        await wait_for(pilot, lambda: panel._current_term == "B")
        panel._travel_forward("C")
        await wait_for(pilot, lambda: panel._current_term == "C")
        assert panel._trail == ["A", "B"]

        await pilot.press("h")
        await wait_for(pilot, lambda: panel._current_term == "B")
        assert panel._trail == ["A"]

        await pilot.press("h")
        await wait_for(pilot, lambda: panel._current_term == "A")
        assert panel._trail == []


async def test_back_on_empty_trail_is_a_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    entries = (_entry(0, "Agent Hood"),)
    _install_fixed_load(monkeypatch, (ref,), {"sase": _snapshot(ref, entries)})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("h")
        await pilot.pause()
        assert panel._current_term == "Agent Hood"
        assert panel._trail == []


async def test_trail_is_bounded_at_32(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = _ref("sase", "sase")
    terms = [f"Term{index:02d}" for index in range(41)]
    entries = tuple(_entry(index, term) for index, term in enumerate(terms))
    _install_fixed_load(monkeypatch, (ref,), {"sase": _snapshot(ref, entries)})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_term == terms[0]

        for term in terms[1:]:
            panel._travel_forward(term)
        await pilot.pause()

        assert panel._current_term == terms[-1]
        assert len(panel._trail) == 32
        assert panel._trail[0] == terms[8]
        assert panel._trail[-1] == terms[39]


async def test_project_cycling_clears_the_trail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = _ref("proj-a", "Alpha")
    ref_b = _ref("proj-b", "Beta")
    entries_a = (_entry(0, "A"), _entry(1, "B"))
    snapshots = {
        "proj-a": _snapshot(ref_a, entries_a, reverse_references={0: ("B",)}),
        "proj-b": _snapshot(ref_b, (_entry(0, "Only In Beta"),)),
    }
    _install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._travel_forward("B")
        await wait_for(pilot, lambda: panel._current_term == "B")
        assert panel._trail == ["A"]

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 1)
        assert panel._trail == []


async def test_back_skips_a_deleted_trail_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    entries = (_entry(0, "Real"), _entry(1, "Other"))
    _install_fixed_load(monkeypatch, (ref,), {"sase": _snapshot(ref, entries)})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._trail = ["Real", "Ghost"]

        await pilot.press("h")
        await wait_for(pilot, lambda: panel._current_term == "Real")
        assert panel._trail == []


async def test_reverse_references_make_inbound_only_term_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    entries = (_entry(0, "Leaf"), _entry(1, "Referencer"))
    snapshot = _snapshot(ref, entries, reverse_references={0: ("Referencer",)})
    _install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPanel()
    app = _GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_term == "Leaf"
        assert panel._chip_outbound_count == 0
        assert [entry.term for entry in panel._chip_entries] == ["Referencer"]
