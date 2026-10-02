"""Tests for the Memory panel history entry points (phase `memory-panel`)."""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from sase.ace.tui.keymaps.app_keymaps import MemoryPanelKeymaps
from sase.ace.tui.keymaps.bindings import build_memory_bindings, memory_help_bindings
from sase.ace.tui.modals.memory_panel_history import (
    fetch_history_summary,
    history_cache_key,
    _history_scope_for_panel_ref,
    history_value_text,
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


def test_history_row_format_uses_versions_and_provenance() -> None:
    value = history_value_text(_summary(), accent="#87D7FF")
    assert "2 versions" in value.plain
    assert "changed" in value.plain
    assert "sase-1bc.12" in value.plain
    # The mini sparkline reuses the pager sparkline cells.
    assert any(cell in value.plain for cell in "▁▂▃▄▅▆▇█")


def test_history_row_shows_amber_untracked_and_dim_loading() -> None:
    loading = history_value_text(None, accent="#87D7FF")
    assert loading.plain == "…"
    assert str(loading.style) == "dim"
    untracked = history_value_text(
        _summary(state="untracked", versions=[]), accent="#87D7FF"
    )
    assert untracked.plain == "untracked"
    assert str(untracked.style) == "yellow"


def test_history_value_reuses_pager_sparkline() -> None:
    value = history_value_text(_summary(), accent="#87D7FF")
    assert isinstance(value, Text)
    assert "2 versions" in value.plain
    assert any(cell in value.plain for cell in "▁▂▃▄▅▆▇█")


def test_note_property_grid_includes_history_row() -> None:
    note = memory_note("gotchas")
    grid = _build_note_property_grid(
        note,
        child_count=0,
        stats=None,
        digest=None,
        read_summary=None,
        source_path="/tmp/sase/memory/gotchas.md",
        accent="#fff",
        history=history_value_text(_summary(), accent="#fff"),
    )
    # Type, Parent, Children, History, Source.
    assert grid.row_count == 5
    console = Console(width=120, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(grid)
    text = capture.get()
    assert "History" in text
    assert "2 versions" in text


def test_note_card_meta_carries_history_for_notes() -> None:
    ref = scope_ref("sase", "sase")
    note = memory_note("gotchas", description="Gotchas.")
    snapshot = scope_snapshot(ref, (note,))
    rendered = build_note_card_meta(
        snapshot,
        note,
        accent="#87D7FF",
        history=history_value_text(_summary(), accent="#87D7FF"),
    )
    console = Console(width=120, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(rendered)
    assert "History" in capture.get()


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
        rendered = pane._history_renderable_for_node(node)
    finally:
        history_module.fetch_history_summary = original
    assert isinstance(rendered, Text)
    assert rendered.plain == "…"
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
    rendered = pane._history_renderable_for_node(node)
    assert isinstance(rendered, Text) and rendered.plain == "…"
    assert len(scheduled) == 1
    event = SimpleNamespace(
        state=WorkerState.SUCCESS,
        worker=SimpleNamespace(result=(key[0], key[1], None)),
    )
    pane._on_history_state_changed(event)  # type: ignore[arg-type]
    assert key in pane._history_failed

    # Later renders keep the retry row without scheduling again.
    scheduled.clear()
    rendered = pane._history_renderable_for_node(node)
    assert isinstance(rendered, Text)
    assert rendered.plain == "history unavailable · r retry"
    assert scheduled == []

    # A scope reload clears the miss so a repaired checkout retries.
    pane._history_request = None
    pane._history_worker = None
    pane._history_failed.clear()
    rendered = pane._history_renderable_for_node(node)
    assert isinstance(rendered, Text) and rendered.plain == "…"
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


def _prepare_history_panel(monkeypatch) -> tuple:
    """Build a loaded ``MemoryPane`` with the history open path stubbed."""
    from types import SimpleNamespace

    from textual.screen import Screen
    from textual.widgets import Static

    from sase.ace.tui.modals.memory_pane import MemoryPane
    from tests.ace.tui.modals.memory_panel_test_helpers import (
        MemoryPanelTestApp,
        install_fixed_load,
    )

    ref = scope_ref("sase", "sase")
    snapshots = {
        "sase": scope_snapshot(ref, (memory_note("gotchas"), memory_note("zebra")))
    }
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


async def test_open_changes_key_opens_feed_pager(
    monkeypatch,
) -> None:
    """Pressing ``C`` opens the changes feed instead of failing silently."""
    from types import SimpleNamespace

    from sase.ace.testing import wait_for

    panel, app, pushed, service = _prepare_history_panel(monkeypatch)
    sentinel = object()
    service.feed = lambda _scopes, **_kwargs: []
    import sase.memory.history.feed_document as feed_document_module

    monkeypatch.setattr(
        feed_document_module,
        "build_feed_document",
        lambda _feed, _label: SimpleNamespace(document=sentinel),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("C")
        await wait_for(pilot, lambda: len(pushed) == 1)
        assert pushed[0].document is sentinel


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
