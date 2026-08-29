"""Load, scope-cycling, picking, and empty-state behavior for the Memory panel."""

from __future__ import annotations

from pathlib import Path
import threading

import pytest
from textual.app import ComposeResult
from textual.widgets import Input

from sase.ace.testing import wait_for
from sase.ace.tui.current_project_settings import CurrentProjectSettings
from sase.ace.tui.modals import memory_pane as memory_pane_module
from sase.ace.tui.modals.memory_pane import MemoryPane, MemoryPaneSession
from sase.ace.tui.modals.memory_panel_load import (
    MemoryPanelInitialLoad,
    MemoryPanelStrandRead,
    MemoryScopeChoice,
)
from sase.ace.tui.modals.memory_panel_scope_picker import MemoryScopePicker
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent
from sase.memory.web.models import MemoryStrand, MemoryWeb
from tests.ace.tui.modals.memory_panel_test_helpers import (
    MemoryPanelTestApp,
    install_fixed_load,
    install_fixed_scope_choices,
    memory_note,
    note_row_text,
    panel_static_text,
    scope_ref,
    scope_snapshot,
)


def _strand_read_event(identity: str) -> MemoryReadEvent:
    return MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id="read-alpha",
        timestamp="2026-08-24T12:00:00+00:00",
        project="demo",
        cwd="/tmp/demo",
        canonical_path=identity,
        resolved_path="",
        agent_name="agent-a",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=None,
        reason=f"ACE MemoryPane previewed {identity}",
        byte_count=10,
        frontmatter_stripped=False,
        kind="strand",
        selectors=(identity,),
        resolved_targets=(identity,),
    )


def _web_with_one_strand(root: Path) -> MemoryWeb:
    memory_root = root / "sase" / "memory"
    strand = MemoryStrand(
        root=root,
        memory_root=memory_root,
        web_slug="decisions",
        slug="alpha",
        path=memory_root / "decisions" / "alpha.md",
        relative_path="sase/memory/decisions/alpha.md",
        keyword="Alpha Decision",
        aliases=("alpha",),
        summary="Alpha summary.",
        metadata={"status": "accepted"},
        body="Alpha body.",
        raw_text="---\nsummary: Alpha summary.\n---\nAlpha body.",
        body_start=len("---\nsummary: Alpha summary.\n---\n"),
        frontmatter={"summary": "Alpha summary."},
    )
    return MemoryWeb(
        root=root,
        memory_root=memory_root,
        slug="decisions",
        path=memory_root / "decisions.md",
        relative_path="sase/memory/decisions.md",
        description="Decision index.",
        roster="list",
        roster_label="DECISIONS",
        strand_noun="decision",
        closure="none",
        metadata={},
        body="Descriptor body.",
        raw_text="---\ntype: core\nweb: true\n---\nDescriptor body.",
        body_start=29,
        frontmatter={"type": "core", "web": True},
        strands=(strand,),
    )


async def test_panel_mounts_and_selects_first_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    notes = (
        memory_note("zebra", note_type="core", description="Always loaded."),
        memory_note("agent_hood", description="Hub note."),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        # Tier 1 (core) notes sort before Tier 2 regardless of stem, so the
        # short "zebra" note is selected first even though "agent_hood" is
        # alphabetically earlier.
        assert panel._current_note == "sase/memory/zebra.md"
        assert "zebra" in panel_static_text(panel, "memory-panel-card-title")


async def test_tree_ordering_nests_children_under_their_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    notes = (
        memory_note("always", note_type="core", description="Always loaded."),
        memory_note("hub", description="Hub."),
        memory_note("child", parent="sase/memory/hub.md", description="Child."),
        memory_note("zeta", description="Later root."),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        rows = [(row.note.path.stem, row.depth) for row in panel._all_rows]
        assert rows == [
            ("always", 0),
            ("hub", 0),
            ("child", 1),
            ("zeta", 0),
        ]


async def test_web_expands_and_strand_preview_waits_for_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = scope_ref("sase", "sase", content_root=str(tmp_path))
    descriptor = memory_note(
        "decisions",
        note_type="core",
        description="Decision index.",
        body="Descriptor body.",
    )
    web = _web_with_one_strand(tmp_path)
    install_fixed_load(
        monkeypatch,
        (ref,),
        {"sase": scope_snapshot(ref, (descriptor,), webs=(web,))},
    )
    reads: list[str] = []
    release_read = threading.Event()

    def fake_record(
        _scope: object, *, web_slug: str, strand_slug: str
    ) -> MemoryPanelStrandRead:
        identity = f"{web_slug}:{strand_slug}"
        reads.append(identity)
        release_read.wait(timeout=2)
        return MemoryPanelStrandRead(
            identity=identity,
            event=_strand_read_event(identity),
        )

    monkeypatch.setattr(
        memory_pane_module, "record_memory_panel_strand_read", fake_record
    )

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert [row.identity for row in panel._rows] == ["sase/memory/decisions.md"]
        assert "1 decision" in note_row_text(panel, 0)

        await pilot.press("space")
        await wait_for(
            pilot,
            lambda: (
                [row.identity for row in panel._rows]
                == [
                    "sase/memory/decisions.md",
                    "decisions:alpha",
                ]
            ),
        )
        await pilot.press("s")
        await wait_for(pilot, lambda: panel._current_note == "decisions:alpha")
        await wait_for(
            pilot,
            lambda: panel._strand_read_status.get("decisions:alpha") == "pending",
        )
        assert "Recording audited read" in panel._body_preview_for_node(
            panel._selected_row()
        )
        release_read.set()
        await wait_for(
            pilot, lambda: panel._strand_read_status.get("decisions:alpha") == "ok"
        )

        assert reads == ["decisions:alpha"]
        assert "Alpha body." in panel._body_preview_for_node(panel._selected_row())
        meta = panel_static_text(panel, "memory-panel-card-meta")
        assert "STRAND" in meta
        assert "AUDITED" in meta
        assert "status: accepted" in meta


async def test_failing_strand_read_worker_does_not_crash_the_pane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = scope_ref("sase", "sase", content_root=str(tmp_path))
    descriptor = memory_note(
        "decisions",
        note_type="core",
        description="Decision index.",
        body="Descriptor body.",
    )
    web = _web_with_one_strand(tmp_path)
    install_fixed_load(
        monkeypatch,
        (ref,),
        {"sase": scope_snapshot(ref, (descriptor,), webs=(web,))},
    )

    def failing_record(
        _scope: object, *, web_slug: str, strand_slug: str
    ) -> MemoryPanelStrandRead:
        del web_slug, strand_slug
        raise RuntimeError("boom")

    monkeypatch.setattr(
        memory_pane_module, "record_memory_panel_strand_read", failing_record
    )

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("space")
        await wait_for(
            pilot,
            lambda: (
                [row.identity for row in panel._rows]
                == [
                    "sase/memory/decisions.md",
                    "decisions:alpha",
                ]
            ),
        )
        await pilot.press("s")
        await wait_for(pilot, lambda: panel._current_note == "decisions:alpha")
        await wait_for(
            pilot,
            lambda: (panel._strand_read_status.get("decisions:alpha") or "").startswith(
                "error:"
            ),
        )

        assert app.is_running
        assert "boom" in panel._strand_read_status["decisions:alpha"]
        assert "Could not record audited read" in panel._body_preview_for_node(
            panel._selected_row()
        )


async def test_seed_filters_setting_reaches_initial_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[bool] = []

    def fake_initial_load(
        *,
        launch_workspace: str | None = None,
        initial_scope_key: str | None = None,
        session_scope_key: str | None = None,
        seed_from_current_project: bool = True,
    ) -> MemoryPanelInitialLoad:
        del launch_workspace, initial_scope_key, session_scope_key
        captured.append(seed_from_current_project)
        return MemoryPanelInitialLoad(ring=(), scope_index=0, snapshot=None)

    monkeypatch.setattr(
        memory_pane_module, "load_memory_panel_initial_state", fake_initial_load
    )

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    app._current_project_settings = CurrentProjectSettings(seed_filters=False)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)

    assert captured == [False]


async def test_scope_cycling_orders_by_display_name_and_scopes_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = scope_ref("proj-a", "Alpha")
    ref_b = scope_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": scope_snapshot(ref_a, (memory_note("only_in_alpha"),)),
        "proj-b": scope_snapshot(ref_b, (memory_note("only_in_beta"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._scope_index == 0
        assert [row.note.path.stem for row in panel._rows] == ["only_in_alpha"]

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._scope_index == 1)
        assert [row.note.path.stem for row in panel._rows] == ["only_in_beta"]

        await pilot.press("P")
        await wait_for(pilot, lambda: not panel._loading and panel._scope_index == 0)
        assert [row.note.path.stem for row in panel._rows] == ["only_in_alpha"]


async def test_scope_selection_is_remembered_per_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = scope_ref("proj-a", "Alpha")
    ref_b = scope_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": scope_snapshot(ref_a, (memory_note("aaa"), memory_note("bbb"))),
        "proj-b": scope_snapshot(ref_b, (memory_note("ccc"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("j")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/bbb.md")

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._scope_index == 1)

        await pilot.press("P")
        await wait_for(pilot, lambda: not panel._loading and panel._scope_index == 0)
        assert panel._current_note == "sase/memory/bbb.md"


async def test_scope_picker_switches_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    ref_a = scope_ref("proj-a", "Alpha")
    ref_b = scope_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": scope_snapshot(ref_a, (memory_note("only_in_alpha"),)),
        "proj-b": scope_snapshot(ref_b, (memory_note("only_in_beta"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)
    install_fixed_scope_choices(
        monkeypatch,
        (
            MemoryScopeChoice(key="proj-a", display_name="Alpha", note_count=1),
            MemoryScopeChoice(key="proj-b", display_name="Beta", note_count=1),
        ),
    )

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)

        await pilot.press("ctrl+p")
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryScopePicker))
        await pilot.press("down")
        await pilot.press("enter")

        await wait_for(pilot, lambda: not panel._loading and panel._scope_index == 1)
        assert [row.note.path.stem for row in panel._rows] == ["only_in_beta"]


async def test_no_memory_root_shows_creation_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase", has_memory=False, memory_read_root=None)
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, ())})

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        meta = panel_static_text(panel, "memory-panel-card-meta")
        assert "No memory root for" in meta
        assert "sase" in meta
        assert "will be created" in meta


async def test_empty_scope_with_root_shows_add_invitation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, ())})

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        meta = panel_static_text(panel, "memory-panel-card-meta")
        assert "No memory notes in" in meta
        assert "sase" in meta
        assert "add the first note" in meta


async def test_diagnostics_scope_shows_error(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = scope_ref("sase", "sase")
    snapshot = scope_snapshot(ref, (), diagnostics=("sase/memory: bad layout",))
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert "bad layout" in panel_static_text(panel, "memory-panel-card-meta")


async def test_initial_and_scope_switch_loads_run_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = scope_ref("proj-a", "Alpha")
    ref_b = scope_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": scope_snapshot(ref_a, (memory_note("a"),)),
        "proj-b": scope_snapshot(ref_b, (memory_note("b"),)),
    }
    off_main_thread = install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._scope_index == 1)

    assert off_main_thread == [True, True]


async def test_refresh_invalidates_and_reloads_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    snapshots = {"sase": scope_snapshot(ref, (memory_note("alpha"),))}
    install_fixed_load(monkeypatch, (ref,), snapshots)

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        # Swap in a new snapshot object so we can prove refresh reloaded it.
        snapshots["sase"] = scope_snapshot(
            ref, (memory_note("alpha"), memory_note("beta"))
        )
        await pilot.press("r")
        await wait_for(pilot, lambda: not panel._loading and len(panel._rows) == 2)
        assert [row.note.path.stem for row in panel._rows] == ["alpha", "beta"]


async def test_session_records_scope_and_selected_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    snapshots = {
        "sase": scope_snapshot(ref, (memory_note("aaa"), memory_note("bbb"))),
    }
    install_fixed_load(monkeypatch, (ref,), snapshots)
    session = MemoryPaneSession()
    panel = MemoryPane(session=session)
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert session.scope_key == "sase"
        assert session.note == "sase/memory/aaa.md"
        await pilot.press("j")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/bbb.md")
        assert session.note == "sase/memory/bbb.md"


async def test_explicit_note_seed_overrides_session_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    snapshots = {
        "sase": scope_snapshot(ref, (memory_note("aaa"), memory_note("bbb"))),
    }
    install_fixed_load(monkeypatch, (ref,), snapshots)
    session = MemoryPaneSession(note="sase/memory/aaa.md")
    panel = MemoryPane(initial_note="sase/memory/bbb.md", session=session)
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_note == "sase/memory/bbb.md"


async def test_missing_note_seed_falls_back_to_session_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    snapshots = {
        "sase": scope_snapshot(ref, (memory_note("aaa"), memory_note("bbb"))),
    }
    install_fixed_load(monkeypatch, (ref,), snapshots)
    session = MemoryPaneSession(note="sase/memory/bbb.md")
    panel = MemoryPane(initial_note="sase/memory/gone.md", session=session)
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_note == "sase/memory/bbb.md"


async def test_session_scope_is_used_when_no_explicit_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = scope_ref("proj-a", "Alpha")
    ref_b = scope_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": scope_snapshot(ref_a, (memory_note("only_in_alpha"),)),
        "proj-b": scope_snapshot(ref_b, (memory_note("only_in_beta"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)
    session = MemoryPaneSession(scope_key="proj-b")
    panel = MemoryPane(session=session)
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._scope_index == 1
        assert [row.note.path.stem for row in panel._rows] == ["only_in_beta"]


async def test_vanished_explicit_scope_falls_back_to_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = scope_ref("proj-a", "Alpha")
    ref_b = scope_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": scope_snapshot(ref_a, (memory_note("only_in_alpha"),)),
        "proj-b": scope_snapshot(ref_b, (memory_note("only_in_beta"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)
    session = MemoryPaneSession(scope_key="proj-b")
    panel = MemoryPane(initial_scope_key="gone", session=session)
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._scope_index == 1


async def test_hidden_pane_focus_default_does_not_steal_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(
        monkeypatch, (ref,), {"sase": scope_snapshot(ref, (memory_note("alpha"),))}
    )
    panel = MemoryPane()

    class _HostApp(MemoryPanelTestApp):
        def compose(self) -> ComposeResult:
            yield panel
            yield Input(id="other-focus")

    app = _HostApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        other = app.query_one("#other-focus", Input)
        other.focus()
        await wait_for(pilot, lambda: other.has_focus)
        panel.on_center_tab_visibility_changed(False)
        panel.focus_default()
        assert other.has_focus
        panel.on_center_tab_visibility_changed(True)
        await wait_for(pilot, lambda: panel._note_list().has_focus)
