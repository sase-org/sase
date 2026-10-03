"""Tests for ACE prompt catalog snapshot helpers."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from sase.ace.tui import prompt_catalog
from sase.ace.tui.actions._startup_prompt_catalog import StartupPromptCatalogMixin
from tests.ace.tui._prompt_catalog_test_helpers import entry


def test_app_prompt_catalog_returns_stable_assist_list_until_snapshot_changes() -> None:
    class CatalogApp(StartupPromptCatalogMixin):
        def _ensure_prompt_catalog_project(self, project: str | None) -> None:
            del project

        def _schedule_prompt_catalog_token_fallback_check(self) -> None:
            pass

    app = CatalogApp()
    app._prompt_catalog = prompt_catalog.PromptCatalogSnapshot(
        generation=1,
        source_token=("first",),
        explicit_snippets={},
        snippets={},
        user_snippets={},
        assist_entries_by_project={None: (entry("review"),)},
    )
    app._prompt_catalog_assist_entries_cache = {}

    first = app.get_prompt_catalog_assist_entries(None)
    second = app.get_prompt_catalog_assist_entries(None)

    assert first is second

    app._prompt_catalog = prompt_catalog.PromptCatalogSnapshot(
        generation=2,
        source_token=("second",),
        explicit_snippets={},
        snippets={},
        user_snippets={},
        assist_entries_by_project={None: (entry("ship"),)},
    )
    app._prompt_catalog_assist_entries_cache = {}
    refreshed = app.get_prompt_catalog_assist_entries(None)

    assert refreshed is not first
    assert refreshed is not None
    assert refreshed[0].name == "ship"


def test_exact_warm_catalog_does_not_fallback_to_default_project() -> None:
    class CatalogApp(StartupPromptCatalogMixin):
        def _ensure_prompt_catalog_project(self, project: str | None) -> None:
            del project

        def _schedule_prompt_catalog_token_fallback_check(self) -> None:
            pass

    app = CatalogApp()
    app._prompt_catalog = prompt_catalog.PromptCatalogSnapshot(
        generation=1,
        source_token=("first",),
        explicit_snippets={},
        snippets={},
        user_snippets={},
        assist_entries_by_project={None: (entry("global"),)},
    )
    app._prompt_catalog_assist_entries_cache = {}

    assert app.get_prompt_catalog_assist_entries("project", schedule=False) is not None
    assert app.get_warm_prompt_catalog_assist_entries_exact("project") is None
    exact_default = app.get_warm_prompt_catalog_assist_entries_exact(None)
    assert exact_default is not None
    assert exact_default[0].name == "global"


def test_fresh_snapshot_retires_only_matching_pending_saves() -> None:
    class CatalogApp(StartupPromptCatalogMixin):
        def _refresh_visible_prompt_catalog_surfaces(self) -> None:
            pass

    app = CatalogApp()
    app._prompt_catalog_generation = 4
    app._pending_snippet_saves = {"applied": "body", "source_only": "later"}
    app._prompt_catalog_assist_entries_cache = {}
    app._user_snippets = {}
    app._snippets_cache = {"older": "value"}

    app._apply_prompt_catalog_snapshot(
        prompt_catalog.PromptCatalogSnapshot(
            generation=4,
            source_token=("fresh",),
            explicit_snippets={
                "applied": "body",
                "source_only": "later",
            },
            snippets={"applied": "body", "source_only": "later"},
            user_snippets={"applied": "body"},
            assist_entries_by_project={None: ()},
        )
    )

    assert app._pending_snippet_saves == {"source_only": "later"}
    assert app._user_snippets == {"applied": "body"}
    assert app._snippets_cache == {"applied": "body", "source_only": "later"}


def test_older_catalog_generation_cannot_erase_pending_save() -> None:
    class CatalogApp(StartupPromptCatalogMixin):
        def _refresh_visible_prompt_catalog_surfaces(self) -> None:
            raise AssertionError("stale snapshots must not refresh widgets")

    app = CatalogApp()
    app._prompt_catalog_generation = 5
    app._pending_snippet_saves = {"saved": "live"}
    app._snippets_cache = {"saved": "live"}

    app._apply_prompt_catalog_snapshot(
        prompt_catalog.PromptCatalogSnapshot(
            generation=4,
            source_token=("old",),
            explicit_snippets={"old": "catalog"},
            snippets={"old": "catalog"},
            user_snippets={"old": "catalog"},
            assist_entries_by_project={None: ()},
        )
    )

    assert app._snippets_cache == {"saved": "live"}
    assert app._pending_snippet_saves == {"saved": "live"}


async def test_catalog_rebuild_coalescing_keeps_queued_config_dirty(
    monkeypatch,
) -> None:
    workers: list[Any] = []
    dirty_calls: list[bool] = []

    class CatalogApp(StartupPromptCatalogMixin):
        def run_worker(self, worker: Any, **_kwargs: object) -> None:
            workers.append(worker)

        def notify(self, *_args: object, **_kwargs: object) -> None:
            pass

    app = CatalogApp()
    app._prompt_catalog = None
    app._prompt_catalog_generation = 1
    app._prompt_catalog_projects = {None}
    app._pending_snippet_saves = {}
    app._prompt_catalog_rebuild_in_flight = False
    app._prompt_catalog_rebuild_pending = False
    app._prompt_catalog_rebuild_pending_force = False
    app._prompt_catalog_rebuild_pending_config_dirty = False

    def _build(**kwargs: object) -> None:
        dirty_calls.append(bool(kwargs["config_dirty"]))
        return None

    monkeypatch.setattr(prompt_catalog, "build_prompt_catalog_snapshot", _build)

    app._schedule_prompt_catalog_rebuild(reason="first")
    app._schedule_prompt_catalog_rebuild(reason="watcher", config_dirty=True)
    assert len(workers) == 1

    await workers.pop(0)()
    assert len(workers) == 1
    await workers.pop(0)()

    assert dirty_calls == [False, True]


async def test_catalog_loading_worker_does_not_block_event_loop(monkeypatch) -> None:
    entered = threading.Event()
    release = threading.Event()

    class CatalogApp(StartupPromptCatalogMixin):
        def notify(self, *_args: object, **_kwargs: object) -> None:
            pass

    app = CatalogApp()
    app._prompt_catalog_rebuild_in_flight = True
    app._prompt_catalog_rebuild_pending = False
    app._prompt_catalog_rebuild_pending_force = False
    app._prompt_catalog_rebuild_pending_config_dirty = False

    def _build(**_kwargs: object) -> None:
        entered.set()
        release.wait(timeout=1.0)
        return None

    monkeypatch.setattr(prompt_catalog, "build_prompt_catalog_snapshot", _build)
    task = asyncio.create_task(
        app._run_prompt_catalog_rebuild(1, frozenset({None}), None, {}, False)
    )
    try:
        await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=0.5)
        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await asyncio.wait_for(heartbeat.wait(), timeout=0.05)
    finally:
        release.set()
        await task
