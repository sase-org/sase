"""Tests for the Timeline lens (phase `timeline-lens`).

Covers the pure lens builders (kit picker rows with markers, hidden
handling, base ordering and ``Same version``, header/footer text) and
the mixin behaviors that do not need a running app (base set/clear,
hidden toggle, cursor revision mapping, the pager hand-off carrying
pin/view/base). Headless rail tests mount the production host
(``MemoryPane``) with a deterministic stub history service.
"""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.keymaps.app_keymaps import MemoryPanelKeymaps
from sase.ace.tui.modals.memory_pane_lens import (
    _NotesSnapshot,
    lens_header_text,
)
from sase.ace.tui.modals.memory_pane_timeline_lens import (
    MemoryPaneTimelineLensMixin,
    _timeline_compare_text,
    _timeline_hidden_rows,
    _timeline_hidden_summary_text,
    _timeline_lens_footer,
    _timeline_lens_header_detail,
    _timeline_lens_rows,
    _timeline_row_id,
    _timeline_subject_display,
)


def _row(ordinal: int, **override: object) -> dict:
    base: dict = {
        "ordinal": ordinal,
        "commit": f"{ordinal:040d}",
        "committer_time": 1790085780,
        "class": "authored",
        "hidden": False,
        "summary": {"words_added": 3, "words_removed": 1},
        "provenance": {"agent": "athena", "bead": "sase-1ev.6"},
        "cause": {},
        "path": "sase/memory/gotchas.md",
        "blob_oid": f"blob{ordinal}",
    }
    base.update(override)
    return base


def _timeline(*rows: dict, **override: object) -> dict:
    base: dict = {
        "selector": "sase/memory/gotchas.md",
        "scope_key": "project:sase",
        "state": "tracked",
        "versions": list(rows),
        "total": len(rows),
        "dirty": False,
    }
    base.update(override)
    return base


def test_lens_rows_list_now_first_and_skip_hidden() -> None:
    timeline = _timeline(_row(1), _row(2, hidden=True), _row(3))
    listed, hidden_count, total = _timeline_lens_rows(
        timeline, now_epoch=1790769600, show_hidden=False
    )
    assert total == 3
    assert hidden_count == 1
    assert listed[0]["label"] == "now"
    labels = [row["label"] for row in listed]
    assert labels == ["now", "v1", "v3"]


def test_lens_rows_show_hidden_on_toggle() -> None:
    timeline = _timeline(_row(1), _row(2, hidden=True), _row(3))
    listed, hidden_count, _ = _timeline_lens_rows(
        timeline, now_epoch=1790769600, show_hidden=True
    )
    assert hidden_count == 1
    assert [row["label"] for row in listed] == ["now", "v1", "v2", "v3"]


def test_lens_rows_survive_missing_timeline() -> None:
    assert _timeline_lens_rows(None, now_epoch=0, show_hidden=False) == ((), 0, 0)
    assert _timeline_lens_rows({}, now_epoch=0, show_hidden=False)[2] == 0


def test_hidden_summary_counts_through_kit() -> None:
    timeline = _timeline(
        _row(1), _row(2, **{"class": "moved"}), _row(3, **{"class": "reflow"})
    )
    hidden = _timeline_hidden_rows(timeline, now_epoch=1790769600)
    assert len(hidden) == 2
    text = _timeline_hidden_summary_text(hidden)
    assert "2 hidden" in text
    assert ". show" in text
    assert _timeline_hidden_summary_text(()) == ""


def test_compare_orders_older_to_newer() -> None:
    assert _timeline_compare_text(24, 21) == "Compare v21 → v24 · b clear"
    assert _timeline_compare_text(21, 24) == "Compare v21 → v24 · b clear"
    assert _timeline_compare_text(0, 21) == "Compare v21 → now · b clear"


def test_compare_same_version() -> None:
    assert _timeline_compare_text(24, 24) == "Same version · b clear"
    assert _timeline_compare_text(0, 0) == "Same version · b clear"
    assert _timeline_compare_text(24, None) is None


def test_header_detail_counts_versions_and_hidden() -> None:
    assert (
        _timeline_lens_header_detail(
            total_committed=25, hidden_count=3, show_hidden=False
        )
        == "25 versions · 3 hidden"
    )
    assert (
        _timeline_lens_header_detail(
            total_committed=1, hidden_count=0, show_hidden=False
        )
        == "1 version"
    )
    assert (
        _timeline_lens_header_detail(
            total_committed=25, hidden_count=3, show_hidden=True
        )
        == "25 versions"
    )


def test_lens_header_names_scope_and_subject() -> None:
    header = lens_header_text(
        lens="timeline",
        scope_display_name="sase",
        subject_display="gotchas",
        detail="25 versions · 3 hidden",
    )
    assert header == "MEMORY · sase › gotchas · timeline · 25 versions · 3 hidden"
    assert lens_header_text(lens="notes", scope_display_name="sase") == ""


def test_subject_display_stems_notes_and_keeps_strands() -> None:
    assert (
        _timeline_subject_display(SimpleNamespace(identity="sase/memory/gotchas.md"))
        == "gotchas"
    )
    assert (
        _timeline_subject_display(SimpleNamespace(identity="glossary:stitch"))
        == "glossary:stitch"
    )


def test_lens_footer_names_configured_keys() -> None:
    footer = _timeline_lens_footer(MemoryPanelKeymaps(), compare_text=None)
    assert "@ notes" in footer
    assert "b base" in footer
    assert ". hidden" in footer
    assert "open in pager" in footer
    with_base = _timeline_lens_footer(
        MemoryPanelKeymaps(), compare_text="Compare v21 → v24 · b clear"
    )
    assert "Compare v21 → v24 · b clear" in with_base


def test_timeline_row_ids_are_stable() -> None:
    assert _timeline_row_id("v24", "authored", 24) == "timeline:v24:authored:24"
    assert _timeline_row_id("now", "", 0) == "timeline:now::0"


def _stub_mixin(**state: object) -> SimpleNamespace:
    """Return a stub carrying the real lens methods over fake siblings."""
    from sase.ace.tui.modals.memory_pane_lens import (  # noqa: PLC0415
        MemoryPaneLensMixin,
    )

    stub = SimpleNamespace(
        _lens="timeline",
        _lens_snapshot=None,
        _timeline_base=None,
        _timeline_cursor=0,
        _timeline_filter="",
        _timeline_has_hidden_line=False,
        _timeline_listed=(),
        _timeline_open_key=None,
        _timeline_preview_pending=False,
        _timeline_rows_all=(),
        _timeline_scheduled=-1,
        _timeline_show_hidden=False,
        _timeline_subject_identity="sase/memory/gotchas.md",
        _timeline_subject_key=("project:sase", "sase/memory/gotchas.md"),
        _timeline_subject_node=SimpleNamespace(identity="sase/memory/gotchas.md"),
        _time_diff_view=False,
        notices=[],
    )
    for name in (
        "action_history_compare_base",
        "action_history_toggle_hidden",
        "_history_diff_carry",
        "_history_explicit_base",
        "_history_initial_revision",
        "_timeline_cursor_row",
        "_timeline_ordinal_for_row",
        "_timeline_rebuild_rows",
        "_timeline_row_index_for_ordinal",
    ):
        setattr(stub, name, getattr(MemoryPaneTimelineLensMixin, name).__get__(stub))
    for name in ("_lens_name", "_lens_is_timeline"):
        setattr(stub, name, getattr(MemoryPaneLensMixin, name).__get__(stub))
    for attr, value in state.items():
        setattr(stub, attr, value)
    return stub


def test_base_set_clears_on_repeat_press() -> None:
    stub = _stub_mixin()
    stub._timeline_listed = (
        {"ordinal": 0, "label": "now", "class": "", "pseudo": True},
        {"ordinal": 24, "label": "v24", "class": "authored", "pseudo": False},
    )
    stub._timeline_cursor = 1
    stub._render_timeline_rail = lambda: None  # type: ignore[attr-defined]
    stub._update_footer = lambda: None  # type: ignore[attr-defined]
    stub.notify = lambda message, **kwargs: stub.notices.append(str(message))  # type: ignore[attr-defined]
    stub.action_history_compare_base()
    assert stub._timeline_base == 24
    stub.action_history_compare_base()
    assert stub._timeline_base is None
    assert any("cleared" in notice for notice in stub.notices)


def test_base_orders_older_to_newer_in_footer() -> None:
    stub = _stub_mixin(_timeline_base=21)
    assert _timeline_compare_text(24, stub._timeline_base) == (
        "Compare v21 → v24 · b clear"
    )
    assert _timeline_compare_text(24, 24) == "Same version · b clear"


def test_hidden_toggle_rebuilds_and_keeps_cursor() -> None:
    timeline = _timeline(_row(1), _row(2, hidden=True), _row(3))
    stub = _stub_mixin()
    stub._timeline_subject_node = SimpleNamespace(identity="x")
    stub._time_timeline = lambda node: dict(timeline)  # type: ignore[attr-defined]
    stub._timeline_listed = ()
    stub._timeline_cursor = 0
    stub._render_timeline_rail = lambda: None  # type: ignore[attr-defined]
    stub._update_header = lambda: None  # type: ignore[attr-defined]
    stub._update_footer = lambda: None  # type: ignore[attr-defined]
    stub._timeline_rebuild_rows(timeline)
    assert [row["label"] for row in stub._timeline_listed][:2] == ["now", "v1"]
    stub.action_history_toggle_hidden()
    assert stub._timeline_show_hidden is True
    assert "v2" in [row["label"] for row in stub._timeline_listed]


def test_cursor_revision_maps_now_staged_and_versions() -> None:
    stub = _stub_mixin()
    stub._timeline_listed = (
        {"ordinal": 0, "label": "now", "class": "", "pseudo": True},
        {"ordinal": 0, "label": "stg", "class": "staged", "pseudo": True},
        {"ordinal": 24, "label": "v24", "class": "authored", "pseudo": False},
    )
    stub._timeline_cursor = 0
    assert stub._history_initial_revision() == "now"
    stub._timeline_cursor = 1
    assert stub._history_initial_revision() == "staged"
    stub._timeline_cursor = 2
    assert stub._history_initial_revision() == "v24"


def test_now_and_staged_stay_independently_selectable() -> None:
    rows = (
        {"ordinal": 0, "label": "now", "class": "", "pseudo": True},
        {"ordinal": 0, "label": "stg", "class": "staged", "pseudo": True},
        {"ordinal": 3, "label": "v3", "class": "authored", "pseudo": False},
    )
    stub = _stub_mixin(_timeline_listed=rows)
    assert stub._timeline_row_index_for_ordinal(0) == 0
    assert stub._timeline_cursor_row()["label"] == "now"
    stub._timeline_cursor = 1
    assert stub._timeline_cursor_row()["label"] == "stg"


def test_diff_carry_uses_lens_base_and_view() -> None:
    stub = _stub_mixin(_timeline_base=21, _time_diff_view=True)
    assert stub._history_diff_carry() == ("diff", "v21")
    assert stub._history_explicit_base() is True
    stub2 = _stub_mixin(_timeline_base=None, _time_diff_view=False)
    assert stub2._history_diff_carry() == ("read", None)
    assert stub2._history_explicit_base() is False


def test_explicit_base_reaches_the_pager_pin_for_now() -> None:
    from sase.memory.history.pager_provider_document import (  # noqa: PLC0415
        build_history_document,
    )

    class _Service:
        def version(self, _scope, _selector, revision, include_body=False):
            assert revision in ("now", "staged", "v3")
            return {
                "existed": True,
                "body": "body",
                "version": {"ordinal": 0, "commit": None, "blob_oid": None},
            }

    scope = SimpleNamespace(scope_key="project:sase", repo_root="/tmp/x")
    document = build_history_document(
        scope=scope,
        subject="sase/memory/gotchas.md",
        initial_revision="now",
        view="diff",
        compare_base="v21",
        explicit_base=True,
        service=_Service(),  # type: ignore[arg-type]
        title="gotchas",
    )
    pin = document.sections[0].version_pin
    assert pin is not None
    assert pin.ordinal == 0
    assert pin.compare_base == 21
    assert pin.explicit_base is True


def test_no_explicit_base_keeps_notes_handoff_unchanged() -> None:
    from sase.memory.history.pager_provider_document import (  # noqa: PLC0415
        build_history_document,
    )

    class _Service:
        def version(self, _scope, _selector, revision, include_body=False):
            return {
                "existed": True,
                "body": "body",
                "version": {"ordinal": 0, "commit": None, "blob_oid": None},
            }

    scope = SimpleNamespace(scope_key="project:sase", repo_root="/tmp/x")
    document = build_history_document(
        scope=scope,
        subject="sase/memory/gotchas.md",
        initial_revision="now",
        view="diff",
        compare_base="v21",
        service=_Service(),  # type: ignore[arg-type]
        title="gotchas",
    )
    pin = document.sections[0].version_pin
    assert pin is not None
    assert pin.compare_base is None
    assert pin.explicit_base is False


def _lens_wire() -> dict:
    return _timeline(_row(1), _row(2), _row(3))


def _prepare_lens_panel(monkeypatch):  # noqa: ANN001, ANN202
    """Mount ``MemoryPane`` with one note and a stub history service."""
    from textual.screen import Screen
    from textual.widgets import Static

    from sase.ace.tui.modals.memory_pane import MemoryPane
    from tests.ace.tui.modals.memory_panel_test_helpers import (
        MemoryPanelTestApp,
        install_fixed_load,
        memory_note,
        scope_ref,
        scope_snapshot,
    )

    ref = scope_ref("sase", "sase")
    snapshots = {
        "sase": scope_snapshot(ref, (memory_note("gotchas"), memory_note("zebra")))
    }
    install_fixed_load(monkeypatch, (ref,), snapshots)
    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    wire = _lens_wire()
    fake_scope = SimpleNamespace(scope_key="project:sase", repo_root="/tmp")

    class _FakeHistory:
        service = SimpleNamespace()

        def scope_for_ref(self, _ref):
            return fake_scope

        def timeline(self, _scope, _selector, include_hidden=False):
            return dict(wire)

        def version_body(self, _scope, _selector, version):
            return {
                "body": f"body {version}",
                "body_missing": False,
                "blob_oid": f"blob-{version}",
            }

        def comparison(self, _scope, _selector, _base, _target):
            return {"unified_diff": ""}

    monkeypatch.setattr(panel, "_ace_history", lambda: _FakeHistory())

    pushed: list = []

    class _FakePager(Screen):
        def __init__(self, document: object, **_kwargs: object) -> None:
            super().__init__()
            self.document = document
            pushed.append(self)

        def compose(self):  # noqa: ANN202
            yield Static("pager")

    import sase.pager.screen as pager_screen_module
    import sase.pager.syntax_policy as syntax_policy_module

    monkeypatch.setattr(pager_screen_module, "PagerScreen", _FakePager)
    monkeypatch.setattr(
        syntax_policy_module,
        "pager_syntax_session_from_config",
        lambda: SimpleNamespace(syntax_enabled=False),
    )
    return panel, app, pushed


def _rail_texts(panel) -> list[str]:  # noqa: ANN001, ANN202
    from tests.ace.tui.modals.memory_panel_test_helpers import note_row_text

    count = int(panel._note_list().option_count)
    return [note_row_text(panel, index) for index in range(count)]


async def test_timeline_lens_opens_and_esc_restores_notes(monkeypatch) -> None:
    """``@`` turns the rail into the timeline; ``Esc`` restores Notes."""
    from textual.widgets import Static

    from sase.ace.testing import wait_for

    panel, app, _pushed = _prepare_lens_panel(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await wait_for(pilot, lambda: bool(panel._history_latest))
        before = panel._current_note
        await pilot.press("@")
        await pilot.pause()
        assert panel._lens == "timeline"
        texts = _rail_texts(panel)
        assert texts[0].startswith("  now") or "now" in texts[0]
        assert any("v3" in text for text in texts)
        header = panel.query_one("#memory-panel-header", Static)
        assert "timeline" in str(header.content.plain)
        await pilot.press("j")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert panel._lens == "notes"
        assert panel._current_note == before
        restored = _rail_texts(panel)
        assert any("gotchas" in text for text in restored)


async def test_timeline_hidden_toggle_reveals_rows(monkeypatch) -> None:
    """``.`` reveals hidden versions; chip shortcuts stay inert."""
    from sase.ace.testing import wait_for

    panel, app, _pushed = _prepare_lens_panel(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await wait_for(pilot, lambda: bool(panel._history_latest))
        await pilot.press("@")
        await pilot.pause()
        assert panel._lens == "timeline"
        assert panel._pending_numbered_link is False
        await pilot.press(".")
        await pilot.pause()
        # The toggle ran exactly once (no double-fire with the binding).
        assert panel._timeline_show_hidden is True
        assert panel._pending_numbered_link is False
        await pilot.press(".")
        await pilot.pause()
        assert panel._timeline_show_hidden is False


async def test_changes_key_is_inert_in_timeline(monkeypatch) -> None:
    """``C`` does nothing inside the Timeline lens."""
    from sase.ace.testing import wait_for

    panel, app, pushed = _prepare_lens_panel(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await wait_for(pilot, lambda: bool(panel._history_latest))
        await pilot.press("@")
        await pilot.pause()
        await pilot.press("C")
        await pilot.pause()
        assert pushed == []
        assert panel._lens == "timeline"


async def test_pager_handoff_carries_cursor_pin_and_base(monkeypatch) -> None:
    """``H`` in the lens opens the pager at the cursor pin with the base."""
    from sase.ace.testing import wait_for

    panel, app, pushed = _prepare_lens_panel(monkeypatch)
    import sase.memory.history.pager_provider as pager_provider_module

    seen: dict = {}
    sentinel = object()
    monkeypatch.setattr(
        pager_provider_module,
        "build_history_document",
        lambda **kwargs: (seen.update(kwargs), sentinel)[1],
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await wait_for(pilot, lambda: bool(panel._history_latest))
        await pilot.press("@")
        await pilot.pause()
        await pilot.press("j")
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        assert panel._timeline_base == 1
        await pilot.press("j")
        await pilot.pause()
        await pilot.press("H")
        await wait_for(pilot, lambda: len(pushed) == 1)
        assert seen["initial_revision"] == "v2"
        assert seen["compare_base"] == "v1"
        assert seen["view"] == "read"
        assert pushed[0].document is sentinel


async def test_timeline_filter_routes_to_lens_rows(monkeypatch) -> None:
    """``/`` in the lens filters versions, leaving the Notes filter alone."""
    from sase.ace.testing import wait_for

    panel, app, _pushed = _prepare_lens_panel(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await wait_for(pilot, lambda: bool(panel._history_latest))
        await pilot.press("@")
        await pilot.pause()
        await pilot.press("/")
        await pilot.pause()
        await pilot.press("v")
        await pilot.press("1")
        await pilot.pause()
        texts = _rail_texts(panel)
        assert len(texts) == 1
        assert "v1" in texts[0]
        assert panel._filter_text == ""
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert panel._lens == "notes"


def test_notes_snapshot_round_trip_shape() -> None:
    snapshot = _NotesSnapshot(
        scope_index=0,
        selected_identity="sase/memory/gotchas.md",
        filter_text="keys",
        filter_bodies=True,
        expanded_webs=frozenset({"glossary"}),
        rail_row=3,
        trail=("a", "b"),
        card_pin=24,
        diff_view=True,
    )
    assert snapshot.selected_identity == "sase/memory/gotchas.md"
    assert snapshot.card_pin == 24
    assert snapshot.diff_view is True
    assert "glossary" in snapshot.expanded_webs
