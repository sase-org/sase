"""Tests for ACE prompt catalog snapshot helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.ace.tui import prompt_catalog
from sase.ace.tui.actions._startup_prompt_catalog import StartupPromptCatalogMixin
from sase.ace.tui.actions._startup_watchers import StartupWatchersMixin
from tests.ace.tui._prompt_catalog_test_helpers import entry


def test_config_watcher_burst_carries_dirty_signal_to_rebuild() -> None:
    scheduled: list[dict[str, object]] = []

    class _Timer:
        def stop(self) -> None:
            pass

    class WatcherApp(StartupWatchersMixin):
        def set_timer(self, *_args: object, **_kwargs: object) -> _Timer:
            return _Timer()

        def _schedule_prompt_catalog_rebuild(self, **kwargs: object) -> None:
            scheduled.append(kwargs)

    app = WatcherApp()
    app._prompt_source_debounce_timer = None
    app._prompt_source_debounce_config_dirty = False
    app._prompt_catalog_generation = 1

    app._on_prompt_source_change((Path("/tmp/config/sase.yml"),))
    app._fire_prompt_source_debounce()

    assert app._prompt_catalog_generation == 2
    assert scheduled == [{"reason": "prompt_source_change", "config_dirty": True}]


def test_config_watcher_invalidates_repo_mention_catalogs() -> None:
    invalidated: list[str] = []

    class _Timer:
        def stop(self) -> None:
            pass

    class WatcherApp(StartupWatchersMixin):
        def set_timer(self, *_args: object, **_kwargs: object) -> _Timer:
            return _Timer()

        def _schedule_prompt_catalog_rebuild(self, **_kwargs: object) -> None:
            return None

        def _invalidate_prompt_glossary_catalogs(self, *, reason: str) -> None:
            invalidated.append(f"glossary:{reason}")

        def _invalidate_prompt_repo_mention_catalogs(self, *, reason: str) -> None:
            invalidated.append(f"repo:{reason}")

    app = WatcherApp()
    app._prompt_source_debounce_timer = None
    app._prompt_source_debounce_config_dirty = False
    app._prompt_catalog_generation = 1

    app._on_prompt_source_change((Path("/tmp/config/sase.yml"),))
    app._fire_prompt_source_debounce()

    assert invalidated == [
        "glossary:prompt_source_change",
        "repo:prompt_source_change",
    ]


def test_warm_prompt_repo_mention_catalog_schedules_once() -> None:
    from sase.ace.tui.repo_mention_catalog import PromptRepoMentionContext

    workers: list[object] = []

    class CatalogApp(StartupPromptCatalogMixin):
        def run_worker(self, callback: object, **_kwargs: object) -> None:
            workers.append(callback)

    app = CatalogApp()
    app._prompt_repo_mention_generation = 0
    app._prompt_repo_mention_catalogs_by_context = {}
    app._prompt_repo_mention_diagnostics_by_context = {}
    app._prompt_repo_mention_warming_contexts = set()
    context = PromptRepoMentionContext(project_ref="sase", launch_workspace=None)

    app.warm_prompt_repo_mention_catalog(context)
    app.warm_prompt_repo_mention_catalog(context)

    assert len(workers) == 1
    assert context in app._prompt_repo_mention_warming_contexts


class _FakePromptSourceWatcher:
    """Record ``ensure_watches`` installs without touching inotify."""

    def __init__(self, *, installed: int = 1) -> None:
        self.ensure_calls: list[list[Any]] = []
        self.ensure_result = installed

    def ensure_watches(self, paths: Any) -> int:
        self.ensure_calls.append(list(paths))
        return self.ensure_result


class _WatchGrowthApp(StartupWatchersMixin, StartupPromptCatalogMixin):
    _prompt_source_watcher: Any

    def __init__(self) -> None:
        self._prompt_source_watcher = None
        self._prompt_catalog_projects = {None}
        self._prompt_catalog_generation = 1
        self._prompt_source_watched_projects = set()
        self._prompt_source_watch_growth_in_flight = False
        self._prompt_source_watch_growth_pending = False
        self.workers: list[Any] = []
        self.rebuilds: list[dict[str, object]] = []

    def run_worker(self, worker: Any, **_kwargs: object) -> None:
        self.workers.append(worker)

    def _schedule_prompt_catalog_rebuild(self, **kwargs: object) -> None:
        self.rebuilds.append(kwargs)


def test_prompt_source_watch_growth_is_noop_without_watcher() -> None:
    app = _WatchGrowthApp()

    app._ensure_prompt_catalog_project("sase")

    assert app._prompt_catalog_projects == {None, "sase"}
    assert app.workers == []
    assert app._prompt_source_watch_growth_in_flight is False


async def test_prompt_source_watch_growth_installs_and_reconciles_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = _WatchGrowthApp()
    watcher = _FakePromptSourceWatcher()
    app._prompt_source_watcher = watcher
    new_dir = tmp_path / "xprompts"
    new_dir.mkdir()
    monkeypatch.setattr(
        prompt_catalog,
        "prompt_source_watch_paths",
        lambda _projects: [new_dir],
    )

    app._ensure_prompt_catalog_project("sase")
    assert len(app.workers) == 1

    await app.workers[0]()

    assert watcher.ensure_calls == [[new_dir]]
    assert app.rebuilds == [{"reason": "watch_growth"}]
    assert app._prompt_source_watched_projects == {None, "sase"}
    assert app._prompt_source_watch_growth_in_flight is False
    assert app._prompt_source_watch_growth_pending is False


async def test_prompt_source_watch_growth_discards_replaced_watcher(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = _WatchGrowthApp()
    old = _FakePromptSourceWatcher()
    app._prompt_source_watcher = old
    monkeypatch.setattr(
        prompt_catalog,
        "prompt_source_watch_paths",
        lambda _projects: [tmp_path],
    )

    app._ensure_prompt_catalog_project("sase")
    assert len(app.workers) == 1

    app._prompt_source_watcher = _FakePromptSourceWatcher()
    await app.workers[0]()

    assert old.ensure_calls == []
    assert app.rebuilds == []
    assert app._prompt_source_watched_projects == set()
    assert app._prompt_source_watch_growth_in_flight is False


async def test_prompt_source_watch_growth_coalesces_rapid_ensures(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = _WatchGrowthApp()
    watcher = _FakePromptSourceWatcher()
    app._prompt_source_watcher = watcher
    monkeypatch.setattr(
        prompt_catalog,
        "prompt_source_watch_paths",
        lambda _projects: [tmp_path],
    )

    app._ensure_prompt_catalog_project("p1")
    app._ensure_prompt_catalog_project("p2")

    assert len(app.workers) == 1
    assert app._prompt_source_watch_growth_pending is True

    await app.workers[0]()
    assert len(app.workers) == 2

    await app.workers[1]()

    assert len(watcher.ensure_calls) == 2
    assert app._prompt_source_watch_growth_in_flight is False
    assert app._prompt_source_watch_growth_pending is False


def test_catalog_getters_never_stop_start_or_join_watcher(tmp_path: Path) -> None:
    """Catalog getters stay pure with a live prompt-source watcher."""
    import sys

    import pytest

    from sase.ace.tui.util.fs_watcher import ArtifactWatcher, _libc
    from tests.ace.tui._prompt_key_io_probes import prompt_key_io_probe

    if not sys.platform.startswith("linux") or _libc() is None:
        pytest.skip("inotify is Linux-only and not available in this environment")

    class GetterApp(StartupWatchersMixin, StartupPromptCatalogMixin):
        _prompt_source_watcher: Any

        def __init__(self, watcher: Any) -> None:
            self._prompt_catalog_projects = {None}
            self._prompt_catalog_generation = 1
            self._prompt_catalog = prompt_catalog.PromptCatalogSnapshot(
                generation=1,
                source_token=("first",),
                explicit_snippets={},
                snippets={},
                user_snippets={},
                assist_entries_by_project={None: (entry("global"),)},
            )
            self._prompt_catalog_assist_entries_cache = {}
            self._snippets_cache = {}
            self._prompt_source_watcher = watcher
            self._prompt_source_watcher_active = True
            self._prompt_source_watched_projects = set()
            self._prompt_source_watch_growth_in_flight = False
            self._prompt_source_watch_growth_pending = False
            self.workers: list[Any] = []
            self.rebuilds: list[dict[str, object]] = []

        def run_worker(self, worker: Any, **_kwargs: object) -> None:
            self.workers.append(worker)

        def _schedule_prompt_catalog_rebuild(self, **kwargs: object) -> None:
            self.rebuilds.append(kwargs)

    def schedule(cb: Any) -> None:
        cb()

    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=schedule,
    )
    assert watcher.start() is True
    try:
        app = GetterApp(watcher)
        with prompt_key_io_probe() as counts:
            entries = app.get_prompt_catalog_assist_entries("sase")
            assert entries is not None
            assert entries[0].name == "global"
            assert app.get_warm_prompt_catalog_assist_entries_exact("sase") is None
            app.warm_prompt_catalog_project("other")
        counts.assert_quiet()
        # Watch growth was scheduled off the pump, never run on it — and
        # the second new project coalesced into the in-flight worker.
        assert len(app.workers) == 1
        assert app._prompt_source_watch_growth_pending is True
    finally:
        watcher.stop()
    assert not hasattr(app, "_restart_prompt_source_watcher")
