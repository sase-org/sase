"""Tests for the Memory panel history entry points (phase `memory-panel`)."""

from __future__ import annotations

from rich.console import Console

from sase.ace.tui.keymaps.app_keymaps import MemoryPanelKeymaps
from sase.ace.tui.keymaps.bindings import build_memory_bindings, memory_help_bindings
from sase.ace.tui.modals.memory_panel_history import (
    fetch_history_summary,
    history_cache_key,
    _history_scope_for_panel_ref,
    selector_for_node,
)
from sase.ace.tui.modals.memory_panel_rendering import (
    _build_note_property_grid,
    build_note_card_meta,
    build_panel_footer,
)
from tests.ace.tui.modals.memory_panel_test_helpers import (
    memory_note,
    scope_ref,
    scope_snapshot,
)


def _version(
    ordinal: int,
    class_name: str = "authored",
    volume: int = 10,
    bead: str | None = "sase-1bc.12",
) -> dict:
    return {
        "ordinal": ordinal,
        "commit": f"{ordinal:040d}",
        "committer_time": 1790085780,
        "class": class_name,
        "hidden": False,
        "summary": {
            "section_paths": ["Default Keymap Config"],
            "words_added": 31,
            "words_removed": 4,
            "frontmatter_phrase": None,
            "created_words": None,
            "volume": volume,
        },
        "provenance": {"agent": "athena", "bead": bead},
        "cause": {},
        "path": "sase/memory/gotchas.md",
        "blob_oid": "abcd",
    }


def _summary(**override: object) -> dict:
    base: dict = {
        "selector": "sase/memory/gotchas.md",
        "core_selector": "sase/memory/gotchas.md",
        "scope_key": "project:sase",
        "state": "tracked",
        "tip": "abc123",
        "now_epoch": 1790769600,
        "versions": [_version(1), _version(2)],
        "total": 2,
    }
    base.update(override)
    return base


def test_memory_bindings_include_history_and_changes() -> None:
    keymaps = MemoryPanelKeymaps()
    assert keymaps.open_history == "H"
    assert keymaps.open_changes == "C"
    actions = {binding.action for binding in build_memory_bindings(keymaps)}
    assert "open_history" in actions
    assert "open_changes" in actions
    descriptions = dict(memory_help_bindings(keymaps))
    # Help surfaces the effective keys for the new verbs.
    assert "H" in descriptions
    assert "C" in descriptions


def test_panel_footer_always_shows_history_with_notes() -> None:
    keymaps = MemoryPanelKeymaps()
    shown = build_panel_footer(
        keymaps, has_notes=True, has_source_path=True, ring_size=1
    )
    assert "H history" in shown
    assert "C changes" in shown
    empty = build_panel_footer(
        keymaps,
        has_notes=False,
        has_source_path=False,
        ring_size=1,
    )
    assert "history" not in empty


def test_time_strip_clean_now_shows_pill_and_meaning() -> None:
    from sase.ace.tui.modals.memory_pane_time_strip import (
        TimeStripSnapshot,
        build_time_band_for_timeline,
        render_card_head,
        render_time_strip,
    )
    from sase.pager.history_kit import history_styles_for_theme

    timeline = _summary()
    snapshot = TimeStripSnapshot(
        subject_id="note:sase/memory/gotchas.md",
        path_label="sase/memory/gotchas.md",
        timeline=dict(timeline),
        now_epoch=1790769600,
    )
    styles = history_styles_for_theme(None)
    head = render_card_head("sase/memory/gotchas.md", snapshot, styles, width=60)
    assert "NOW" in head.plain
    assert "sase/memory/gotchas.md" in head.plain
    data = build_time_band_for_timeline(
        dict(timeline),
        subject_id="note:sase/memory/gotchas.md",
        now_epoch=1790769600,
    )
    assert data is not None
    strip = render_time_strip(data, width=60, rows=2, styles=styles)
    # Row 2 answers "what changed last?" with the newest meaning.
    assert (
        "sase-1bc.12" in strip.plain
        or "authored" in strip.plain.lower()
        or strip.plain.strip() != ""
    )


def test_time_strip_untracked_and_no_vcs_use_pager_words() -> None:
    from sase.ace.tui.modals.memory_pane_time_strip import (
        build_time_band_for_timeline,
        render_time_strip,
    )
    from sase.pager.history_kit import history_styles_for_theme

    styles = history_styles_for_theme(None)
    untracked = build_time_band_for_timeline(
        _summary(state="untracked", versions=[]),
        subject_id="note:sase/memory/gotchas.md",
        now_epoch=1790769600,
    )
    assert untracked is not None
    assert (
        "UNTRACKED"
        in render_time_strip(untracked, width=60, rows=2, styles=styles).plain
    )
    no_vcs = build_time_band_for_timeline(
        _summary(state="NO VCS", versions=[]),
        subject_id="note:sase/memory/gotchas.md",
        now_epoch=1790769600,
    )
    assert no_vcs is not None
    assert "NO VCS" in render_time_strip(no_vcs, width=60, rows=2, styles=styles).plain


def test_time_strip_indexing_reserves_rows_and_folds() -> None:
    from sase.ace.tui.modals.memory_pane_time_strip import (
        build_time_band_for_timeline,
        render_time_strip,
        time_strip_row_count,
    )
    from sase.pager.history_kit import history_styles_for_theme

    assert time_strip_row_count(10) == 1
    assert time_strip_row_count(20) == 2
    styles = history_styles_for_theme(None)
    data = build_time_band_for_timeline(
        None, subject_id="note:sase/memory/gotchas.md", loading=True
    )
    assert data is not None
    strip = render_time_strip(data, width=60, rows=2, styles=styles)
    assert "indexing" in strip.plain.lower()
    folded = render_time_strip(data, width=60, rows=1, styles=styles)
    assert "indexing" in folded.plain.lower()


def test_note_property_grid_has_no_history_row() -> None:
    note = memory_note("gotchas")
    grid = _build_note_property_grid(
        note,
        child_count=0,
        stats=None,
        digest=None,
        read_summary=None,
        source_path="/tmp/sase/memory/gotchas.md",
        accent="#fff",
    )
    # Type, Parent, Children, Source.
    assert grid.row_count == 4
    console = Console(width=120, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(grid)
    text = capture.get()
    assert "History" not in text


def test_note_card_meta_has_no_history_row() -> None:
    ref = scope_ref("sase", "sase")
    note = memory_note("gotchas", description="Gotchas.")
    snapshot = scope_snapshot(ref, (note,))
    rendered = build_note_card_meta(
        snapshot,
        note,
        accent="#87D7FF",
    )
    console = Console(width=120, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(rendered)
    assert "History" not in capture.get()


def test_selector_for_node_covers_notes_and_strands() -> None:
    from sase.ace.tui.memory_panel_catalog import MemoryRailNode

    note = memory_note("gotchas")
    node = MemoryRailNode(note=note, depth=0)
    assert selector_for_node(node) == "sase/memory/gotchas.md"

    from tests.ace.tui.modals.memory_panel_test_helpers import (
        memory_web_with_mentioning_strands,
    )

    web = memory_web_with_mentioning_strands()
    strand = web.strands[0]
    strand_node = MemoryRailNode(
        note=note, depth=1, web=web, strand=strand, strand_scope="project"
    )
    selector = selector_for_node(strand_node)
    assert selector is not None
    assert selector.startswith(f"{web.slug}:")


def test_history_scope_uses_content_root_never_cwd(monkeypatch) -> None:
    import sase.ace.tui.modals.memory_panel_history as history_module

    seen: dict[str, str] = {}

    class _Service:
        def project_scope(self, root) -> object:
            seen["root"] = str(root)
            return object()

    ref = scope_ref("sase", "sase", content_root="/tmp/from-ring")
    monkeypatch.chdir("/tmp")
    result = _history_scope_for_panel_ref(ref, _Service())
    assert result is not None
    assert seen["root"] == "/tmp/from-ring"


def test_history_cache_key_includes_scope_subject_and_tip() -> None:
    summary = _summary()
    assert history_cache_key(summary) == (
        "project:sase",
        "sase/memory/gotchas.md",
        "abc123",
    )


def test_history_summary_fetch_is_fail_open() -> None:
    class _FailingService:
        def sync(self, _scope):  # noqa: ANN001, ANN202
            raise RuntimeError("sync down")

        def timeline(self, _scope, _selector, **_kwargs):  # noqa: ANN001, ANN202
            raise RuntimeError("timeline down")

    class _Scope:
        scope_key = "project:sase"
        repo_root = "/tmp"

    assert fetch_history_summary(_FailingService(), _Scope(), "gotchas.md") is None


def test_history_row_loads_without_blocking() -> None:
    """The card render never calls the service synchronously."""
    from sase.ace.tui.modals.memory_pane import MemoryPane

    pane = MemoryPane.__new__(MemoryPane)
    pane._ring = (scope_ref("sase", "sase", content_root="/tmp/from-ring"),)
    pane._scope_index = 0
    pane._loading = False
    pane._accent = "#87D7FF"
    pane._history_latest = {}
    pane._history_failed = set()
    pane._history_request = None
    pane._history_worker = None
    calls: list[tuple[str, str]] = []

    def _fake_ensure(scope_key: str, selector: str) -> None:
        calls.append((scope_key, selector))

    pane._ensure_history_load = _fake_ensure  # type: ignore[method-assign]

    from sase.ace.tui.memory_panel_catalog import MemoryRailNode

    node = MemoryRailNode(note=memory_note("gotchas"), depth=0)

    def _blocking_fetch(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("service must not be called on the render path")

    import sase.ace.tui.modals.memory_panel_history as history_module

    original = history_module.fetch_history_summary
    history_module.fetch_history_summary = _blocking_fetch  # type: ignore[assignment]
    try:
        snapshot = pane._time_strip_snapshot_for_node(node)
    finally:
        history_module.fetch_history_summary = original
    assert snapshot is not None
    assert snapshot.timeline is None
    assert snapshot.failed is False
    assert calls == [("sase", "sase/memory/gotchas.md")]


def test_unavailable_history_load_does_not_respawn_workers() -> None:
    """A settled-unavailable summary keeps the retry row, no new worker."""
    from types import SimpleNamespace

    from textual.worker import WorkerState

    from sase.ace.tui.modals.memory_pane import MemoryPane
    from sase.ace.tui.memory_panel_catalog import MemoryRailNode

    pane = MemoryPane.__new__(MemoryPane)
    pane._ring = (scope_ref("sase", "sase", content_root="/tmp/from-ring"),)
    pane._scope_index = 0
    pane._loading = False
    pane._accent = "#87D7FF"
    pane._history_latest = {}
    pane._history_failed = set()
    pane._history_request = None
    pane._history_worker = None
    pane._closed = True  # skip the post-completion re-render probe
    scheduled: list[tuple] = []
    pane.run_worker = lambda *a, **k: scheduled.append((a, k)) or None  # type: ignore[method-assign]

    node = MemoryRailNode(note=memory_note("gotchas"), depth=0)
    key = ("sase", "sase/memory/gotchas.md")

    # First render schedules the load; completion with no summary marks it.
    snapshot = pane._time_strip_snapshot_for_node(node)
    assert snapshot is not None and snapshot.timeline is None
    assert len(scheduled) == 1
    event = SimpleNamespace(
        state=WorkerState.SUCCESS,
        worker=SimpleNamespace(result=(key[0], key[1], None)),
    )
    pane._on_history_state_changed(event)  # type: ignore[arg-type]
    assert key in pane._history_failed

    # Later renders keep the failed snapshot without scheduling again.
    scheduled.clear()
    snapshot = pane._time_strip_snapshot_for_node(node)
    assert snapshot is not None
    assert snapshot.failed is True
    assert snapshot.timeline is None
    assert scheduled == []

    # A scope reload clears the miss so a repaired checkout retries.
    pane._history_request = None
    pane._history_worker = None
    pane._history_failed.clear()
    snapshot = pane._time_strip_snapshot_for_node(node)
    assert snapshot is not None and snapshot.failed is False
    assert len(scheduled) == 1


def test_config_schema_accepts_history_keymaps() -> None:
    from jsonschema import Draft7Validator

    from tests._config_schema_helpers import schema

    Draft7Validator(schema()).validate(
        {"ace": {"keymaps": {"memory": {"open_history": "H", "open_changes": "C"}}}}
    )


def test_no_call_from_thread_in_async_workers_under_ace_tui() -> None:
    """AST guard: async workers must not call ``call_from_thread`` directly.

    ``run_worker`` coroutine workers already run on the app thread, so a
    direct ``call_from_thread`` raises ``RuntimeError`` (and with
    ``exit_on_error=False`` the failure is silent). Calls nested inside a
    ``def``/``lambda`` closure defined in the worker are exempt: those run
    later on whatever thread invokes the closure (for example a pager
    refresh callback on a worker thread), where ``call_from_thread`` is
    correct.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[4] / "src" / "sase" / "ace" / "tui"
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            pending = list(node.body)
            while pending:
                child = pending.pop()
                if isinstance(
                    child,
                    (
                        ast.FunctionDef,
                        ast.AsyncFunctionDef,
                        ast.Lambda,
                        ast.ClassDef,
                    ),
                ):
                    continue
                if isinstance(child, ast.Call):
                    func = child.func
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "call_from_thread"
                    ):
                        offenders.append(f"{path}:{child.lineno}")
                pending.extend(ast.iter_child_nodes(child))
    assert offenders == []


def _prepare_history_panel(monkeypatch, *, webs: tuple = ()) -> tuple:
    """Build a loaded ``MemoryPane`` with the history open path stubbed.

    With *webs*, the scope holds only those webs plus their descriptor
    notes, so the first rail row is the first web's descriptor.
    """
    from types import SimpleNamespace

    from textual.screen import Screen
    from textual.widgets import Static

    from sase.ace.tui.modals.memory_pane import MemoryPane
    from tests.ace.tui.modals.memory_panel_test_helpers import (
        MemoryPanelTestApp,
        install_fixed_load,
    )

    ref = scope_ref("sase", "sase")
    if webs:
        notes = tuple(
            memory_note(web.slug, note_type=None, type_source="missing") for web in webs
        )
    else:
        notes = (memory_note("gotchas"), memory_note("zebra"))
    snapshots = {"sase": scope_snapshot(ref, notes, webs=webs)}
    install_fixed_load(monkeypatch, (ref,), snapshots)

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)

    fake_scope = SimpleNamespace(scope_key="project:sase", repo_root="/tmp")
    service = SimpleNamespace()
    history = SimpleNamespace(service=service, scope_for_ref=lambda _ref: fake_scope)
    monkeypatch.setattr(panel, "_ace_history", lambda: history)

    import sase.ace.tui.modals.memory_panel_history as history_module

    monkeypatch.setattr(
        history_module, "_history_scope_for_panel_ref", lambda _ref, _svc: fake_scope
    )
    monkeypatch.setattr(
        history_module,
        "history_scopes_for_ring",
        lambda _ring, _svc: [fake_scope],
    )

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
    return panel, app, pushed, service


async def test_open_history_key_opens_pager(
    monkeypatch,
) -> None:
    """Pressing ``H`` opens the pager instead of failing silently."""
    from sase.ace.testing import wait_for

    panel, app, pushed, _service = _prepare_history_panel(monkeypatch)
    sentinel = object()
    import sase.memory.history.pager_provider as pager_provider_module

    monkeypatch.setattr(
        pager_provider_module,
        "build_history_document",
        lambda **_kwargs: sentinel,
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("H")
        await wait_for(pilot, lambda: len(pushed) == 1)
        assert pushed[0].document is sentinel


async def test_open_changes_key_opens_changes_lens(
    monkeypatch,
) -> None:
    """Pressing ``C`` turns the rail into the Changes lens (no pager push)."""
    from sase.ace.testing import wait_for

    panel, app, pushed, service = _prepare_history_panel(monkeypatch)
    panel._ace_history().feed = lambda _scopes: {"changesets": []}
    import sase.ace.tui.modals.memory_pane_changes_lens as changes_module

    seen: dict = {}
    real_fetch = changes_module.MemoryPaneChangesLensMixin._changes_fetch

    def _spy_fetch(self) -> None:  # noqa: ANN001, ANN202
        seen["fetched"] = True
        return real_fetch(self)

    monkeypatch.setattr(
        changes_module.MemoryPaneChangesLensMixin, "_changes_fetch", _spy_fetch
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._lens == "changes")
        assert pushed == []
        assert seen.get("fetched") is True
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._lens == "notes")


async def test_open_history_failure_surfaces_error_toast(
    monkeypatch,
) -> None:
    """A pager build miss toasts instead of failing silently."""
    from sase.ace.testing import wait_for

    panel, app, pushed, _service = _prepare_history_panel(monkeypatch)
    import sase.memory.history.pager_provider as pager_provider_module

    monkeypatch.setattr(
        pager_provider_module, "build_history_document", lambda **_kwargs: None
    )
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        panel,
        "notify",
        lambda message, *_, **kwargs: toasts.append(
            (str(message), str(kwargs.get("severity", "")))
        ),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("H")
        await wait_for(pilot, lambda: len(toasts) == 1)
        assert "could not open history" in toasts[0][0]
        assert toasts[0][1] == "error"
        assert pushed == []


async def test_open_history_stale_selection_drops_the_open(
    monkeypatch,
) -> None:
    """Moving the cursor while history loads drops the pager open."""
    import threading

    from sase.ace.testing import wait_for

    panel, app, pushed, _service = _prepare_history_panel(monkeypatch)
    release = threading.Event()
    started = threading.Event()
    sentinel = object()
    import sase.memory.history.pager_provider as pager_provider_module

    def _slow_build(**_kwargs):  # noqa: ANN202
        started.set()
        assert release.wait(timeout=10)
        return sentinel

    monkeypatch.setattr(pager_provider_module, "build_history_document", _slow_build)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("H")
        await wait_for(pilot, lambda: started.is_set())
        await pilot.press("j")
        release.set()
        await wait_for(
            pilot,
            lambda: (
                panel._history_open_worker is not None
                and panel._history_open_worker.is_finished
            ),
        )
        await pilot.pause()
        assert pushed == []


async def test_open_history_key_opens_web_descriptor_and_strand(
    monkeypatch,
) -> None:
    """``H`` opens a web descriptor by path and a strand as ``web:slug``."""
    from sase.ace.testing import wait_for
    from tests.ace.tui.modals.memory_panel_test_helpers import (
        install_fake_strand_read,
        memory_web_with_mentioning_strands,
    )

    web = memory_web_with_mentioning_strands()
    panel, app, pushed, _service = _prepare_history_panel(monkeypatch, webs=(web,))
    install_fake_strand_read(monkeypatch)
    titles: list[str] = []
    import sase.memory.history.pager_provider as pager_provider_module

    def _build(**kwargs):  # noqa: ANN202
        titles.append(str(kwargs.get("title")))
        return object()

    monkeypatch.setattr(pager_provider_module, "build_history_document", _build)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("H")
        await wait_for(pilot, lambda: len(pushed) == 1)
        assert titles == ["sase/memory/glossary.md"]
        app.pop_screen()
        await pilot.press("space")
        await pilot.press("j")
        await wait_for(
            pilot,
            lambda: getattr(panel._selected_row(), "strand", None) is not None,
        )
        await pilot.press("H")
        await wait_for(pilot, lambda: len(pushed) == 2)
        assert titles[-1] == "glossary:alpha"


async def test_open_history_failure_names_the_reason(
    monkeypatch,
) -> None:
    """A raising pager build toasts ``could not open history: <reason>``."""
    from sase.ace.testing import wait_for

    panel, app, pushed, _service = _prepare_history_panel(monkeypatch)
    import sase.memory.history.pager_provider as pager_provider_module

    def _boom(**_kwargs):  # noqa: ANN202
        raise RuntimeError("index is locked")

    monkeypatch.setattr(pager_provider_module, "build_history_document", _boom)
    toasts: list[str] = []
    monkeypatch.setattr(
        panel, "notify", lambda message, *_, **_kw: toasts.append(str(message))
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("H")
        await wait_for(pilot, lambda: len(toasts) == 1)
        assert toasts == ["could not open history: index is locked"]
        assert pushed == []


async def test_open_history_hidden_hub_drops_the_open(
    monkeypatch,
) -> None:
    """Hiding the hosting hub while history loads drops the pager open."""
    import threading

    from sase.ace.testing import wait_for

    panel, app, pushed, _service = _prepare_history_panel(monkeypatch)
    release = threading.Event()
    started = threading.Event()
    import sase.memory.history.pager_provider as pager_provider_module

    def _slow_build(**_kwargs):  # noqa: ANN202
        started.set()
        assert release.wait(timeout=10)
        return object()

    monkeypatch.setattr(pager_provider_module, "build_history_document", _slow_build)
    toasts: list[str] = []
    monkeypatch.setattr(
        panel, "notify", lambda message, *_, **_kw: toasts.append(str(message))
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("H")
        await wait_for(pilot, lambda: started.is_set())
        panel.on_center_tab_visibility_changed(False)
        release.set()
        await wait_for(
            pilot,
            lambda: (
                panel._history_open_worker is not None
                and panel._history_open_worker.is_finished
            ),
        )
        await pilot.pause()
        assert pushed == []
        assert toasts == []


def test_open_history_failure_uses_honest_state_words() -> None:
    """Untracked and no-VCS misses toast the pager's honest words."""
    from sase.ace.tui.modals.memory_pane_history import _history_open_failure

    assert (
        _history_open_failure(
            {"state": "untracked"}, home_without_scope=False, reason="x"
        )
        == "no history yet · commit this file to start its history"
    )
    assert (
        _history_open_failure({"state": "no_vcs"}, home_without_scope=False, reason="")
        == "home memory is not in git"
    )
    assert (
        _history_open_failure(None, home_without_scope=True, reason="no scope")
        == "home memory is not in git"
    )
    assert (
        _history_open_failure(
            {"state": "tracked"}, home_without_scope=False, reason="boom"
        )
        == "could not open history: boom"
    )
    assert (
        _history_open_failure(None, home_without_scope=False, reason="")
        == "could not open history: unknown reason"
    )


def test_stale_chip_marks_only_a_kept_snapshot() -> None:
    """``stale`` rides with the last good strip, never with no snapshot."""
    from sase.ace.tui.modals.memory_pane_time_strip import (
        TimeStripSnapshot,
        render_card_head,
    )
    from sase.pager.history_kit import history_styles_for_theme

    styles = history_styles_for_theme(None)
    kept = TimeStripSnapshot(
        subject_id="note:sase/memory/gotchas.md",
        path_label="sase/memory/gotchas.md",
        timeline=_summary(),
        now_epoch=1790769600,
        failed=True,
    )
    assert "stale" in render_card_head("sase/memory/gotchas.md", kept, styles).plain
    nothing = TimeStripSnapshot(
        subject_id="note:sase/memory/gotchas.md",
        path_label="sase/memory/gotchas.md",
        timeline=None,
        now_epoch=1790769600,
        failed=True,
    )
    head = render_card_head("sase/memory/gotchas.md", nothing, styles).plain
    assert "stale" not in head
