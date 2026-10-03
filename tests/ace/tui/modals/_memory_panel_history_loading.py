"""History lookup and background-loading tests for the memory panel."""

from __future__ import annotations

import sase.ace.tui.modals.memory_panel_history as history_module
from sase.ace.tui.modals.memory_panel_history import (
    fetch_history_summary,
    history_cache_key,
)
from tests.ace.tui.modals._memory_panel_history_fixtures import history_summary
from tests.ace.tui.modals.memory_panel_test_helpers import memory_note, scope_ref


def test_history_scope_uses_content_root_never_cwd(monkeypatch) -> None:
    seen: dict[str, str] = {}

    class _Service:
        def project_scope(self, root) -> object:
            seen["root"] = str(root)
            return object()

    ref = scope_ref("sase", "sase", content_root="/tmp/from-ring")
    monkeypatch.chdir("/tmp")
    result = history_module._history_scope_for_panel_ref(ref, _Service())
    assert result is not None
    assert seen["root"] == "/tmp/from-ring"


def test_history_cache_key_includes_scope_subject_and_tip() -> None:
    summary = history_summary()
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
