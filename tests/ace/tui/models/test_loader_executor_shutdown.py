from __future__ import annotations

import time
from concurrent.futures import CancelledError
from pathlib import Path
from threading import Condition, Event
from typing import Any

import pytest

from sase.ace import dismissed_agents_bundles
from sase.ace.tui.actions.lifecycle import LifecycleMixin
from sase.ace.tui.models._loaders import (
    _done_loaders,
    _json_cache,
    _workflow_step_loaders,
)
from sase.ace.tui.util import shutdown


def test_shutdown_loader_executor_cancels_pending_and_resets() -> None:
    _json_cache.shutdown_loader_executor()
    release = Event()
    started = 0
    condition = Condition()

    def _block() -> str:
        nonlocal started
        with condition:
            started += 1
            condition.notify_all()
        release.wait(timeout=5)
        return "done"

    executor = _json_cache.get_loader_executor()
    max_workers = executor._max_workers
    running = [executor.submit(_block) for _ in range(max_workers)]

    with condition:
        assert condition.wait_for(lambda: started == max_workers, timeout=2)

    pending = [executor.submit(lambda: "pending") for _ in range(max_workers * 2)]

    try:
        start = time.monotonic()
        _json_cache.shutdown_loader_executor()
        assert time.monotonic() - start < 0.5
        assert all(future.cancelled() for future in pending)
    finally:
        release.set()
        for future in running:
            future.result(timeout=2)
        _json_cache.shutdown_loader_executor()

    fresh = _json_cache.get_loader_executor()
    try:
        assert fresh is not executor
        assert fresh.submit(lambda: "fresh").result(timeout=2) == "fresh"
    finally:
        _json_cache.shutdown_loader_executor()


def test_shutdown_loader_executor_is_noop_without_pool() -> None:
    _json_cache.shutdown_loader_executor()
    _json_cache.shutdown_loader_executor()


def test_lifecycle_do_quit_shuts_down_loader_executor(monkeypatch) -> None:
    calls: list[str] = []
    app = _lifecycle_app(calls)
    monkeypatch.setattr(
        _json_cache,
        "shutdown_loader_executor",
        lambda: calls.append("loader"),
    )

    app._do_quit()

    assert shutdown.is_shutdown_requested() is True
    assert calls.count("loader") == 1
    assert calls.index("loader") < calls.index("exit")


def test_lifecycle_do_quit_exits_after_cleanup_failure(monkeypatch) -> None:
    calls: list[str] = []
    app = _lifecycle_app(calls)
    monkeypatch.setattr(
        _json_cache,
        "shutdown_loader_executor",
        lambda: calls.append("loader"),
    )

    def fail_selection_save() -> None:
        calls.append("selection")
        raise RuntimeError("selection save failed")

    app._save_current_selection = fail_selection_save  # type: ignore[method-assign]

    app._do_quit()

    assert calls[0] == "selection"
    assert "watcher" in calls
    assert "loader" in calls
    assert calls[-1] == "exit"


def test_lifecycle_on_unmount_shuts_down_loader_executor(monkeypatch) -> None:
    calls: list[str] = []
    app = _lifecycle_app(calls)
    monkeypatch.setattr(
        _json_cache,
        "shutdown_loader_executor",
        lambda: calls.append("loader"),
    )

    app.on_unmount()

    assert calls == [
        "watcher",
        "discovery",
        "content-search",
        "loader",
        "restore-decoration",
        "restore-signal",
    ]


class _CancelOnIterationExecutor:
    def map(self, _fn: Any, _items: Any) -> Any:
        def _results() -> Any:
            raise CancelledError
            yield None

        return _results()


class _RuntimeShutdownExecutor:
    def map(self, _fn: Any, _items: Any) -> Any:
        raise RuntimeError("cannot schedule new futures after shutdown")


@pytest.mark.parametrize(
    "executor",
    [
        _CancelOnIterationExecutor(),
        _RuntimeShutdownExecutor(),
    ],
)
def test_loader_consumers_return_empty_during_executor_shutdown(
    tmp_path: Path,
    monkeypatch,
    executor: Any,
) -> None:
    monkeypatch.setattr(_json_cache, "get_loader_executor", lambda: executor)
    monkeypatch.setattr(_workflow_step_loaders, "get_loader_executor", lambda: executor)

    projects_dir = _done_artifact_tree(tmp_path)
    monkeypatch.setattr(_done_loaders, "sase_projects_dir", lambda: projects_dir)
    assert _done_loaders.load_done_agents({}, {}) == []

    timestamp_dir = tmp_path / "project" / "artifacts" / "workflow-test" / "ts"
    assert _workflow_step_loaders.load_workflow_agent_steps(
        timestamp_dirs=[(tmp_path / "project", timestamp_dir)]
    ) == ([], {})

    bundles_dir = tmp_path / "dismissed-bundles"
    bundles_dir.mkdir()
    ctx = _DismissedCtx(bundles_dir)
    assert dismissed_agents_bundles.load_dismissed_bundles(ctx) == []


def _lifecycle_app(calls: list[str]) -> LifecycleMixin:
    app = LifecycleMixin.__new__(LifecycleMixin)
    app.patches = []
    app._stop_artifact_watcher = lambda: calls.append("watcher")
    app._cancel_pending_artifact_file_discovery = lambda: calls.append("discovery")
    app._cancel_pending_content_search_refresh = lambda: calls.append("content-search")
    app._restore_artifact_file_tmux_decoration = lambda notify_warnings=True: (
        calls.append("restore-decoration")
    )
    app._restore_artifact_file_viewer_close_signal_handler = lambda: calls.append(
        "restore-signal"
    )
    app.exit = lambda: calls.append("exit")
    return app


def _done_artifact_tree(tmp_path: Path) -> Path:
    projects_dir = tmp_path / "projects"
    artifact_dir = projects_dir / "home" / "artifacts" / "ace-run" / "20260617120000"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "done.json").write_text("{}", encoding="utf-8")
    return projects_dir


class _DismissedCtx:
    def __init__(self, bundles_dir: Path) -> None:
        self._bundles_dir = bundles_dir

    def _run_dismissed_archive_maintenance(self) -> None:
        pass

    def dismissed_bundles_dir(self) -> Path:
        return self._bundles_dir

    def _iter_bundle_paths(self) -> list[Path]:
        return [self._bundles_dir / "20260617120000.json"]

    def _load_bundle_file(self, _path: Path) -> None:
        raise AssertionError("bundle files should not be loaded after shutdown")
