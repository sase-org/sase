"""Tests for ACE prompt catalog snapshot helpers."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.ace.tui import prompt_catalog
from sase.ace.tui.actions._startup_prompt_catalog import StartupPromptCatalogMixin
from sase.ace.tui.actions._startup_watchers import StartupWatchersMixin
from sase.ace.tui.widgets.xprompt_arg_assist import XPromptAssistEntry
from sase.xprompt.models import XPrompt


def _entry(name: str) -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name=name,
        insertion=f"#{name}",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(),
        content_preview=None,
    )


def test_prompt_source_token_changes_for_xprompt_file_create(
    tmp_path: Path,
    monkeypatch,
) -> None:
    xprompt_dir = tmp_path / ".xprompts"
    xprompt_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(prompt_catalog, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(
        prompt_catalog, "get_xprompt_search_paths", lambda: [xprompt_dir]
    )
    monkeypatch.setattr(prompt_catalog, "current_config_token", lambda: ("config",))

    before = prompt_catalog._prompt_source_token([None])
    (xprompt_dir / "new.md").write_text("hello", encoding="utf-8")
    after = prompt_catalog._prompt_source_token([None])

    assert before != after


def test_prompt_source_token_changes_for_project_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_dir = tmp_path / "config"
    project_dir = config_dir / "xprompts" / "sase"
    project_dir.mkdir(parents=True)
    monkeypatch.setattr(prompt_catalog, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(prompt_catalog, "get_xprompt_search_paths", lambda: [])
    monkeypatch.setattr(prompt_catalog, "current_config_token", lambda: ("config",))

    before = prompt_catalog._prompt_source_token(["sase"])
    (project_dir / "review.yml").write_text("steps: []", encoding="utf-8")
    after = prompt_catalog._prompt_source_token(["sase"])

    assert before != after


def test_prompt_source_token_changes_for_memory_file_create(
    tmp_path: Path,
    monkeypatch,
) -> None:
    memory_dir = tmp_path / "sase" / "memory"
    memory_dir.mkdir(parents=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(prompt_catalog, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(prompt_catalog, "get_xprompt_search_paths", lambda: [])
    monkeypatch.setattr(prompt_catalog, "current_config_token", lambda: ("config",))
    monkeypatch.setattr(
        prompt_catalog,
        "resolve_memory_file_sources",
        lambda **_kwargs: (
            SimpleNamespace(
                paths=SimpleNamespace(candidates=(memory_dir,)),
            ),
        ),
    )

    before = prompt_catalog._prompt_source_token([None])
    (memory_dir / "glossary.md").write_text("---\ntype: short\n---\nbody\n")
    after = prompt_catalog._prompt_source_token([None])

    assert before != after


def test_prompt_source_watch_paths_include_memory_roots(
    tmp_path: Path,
    monkeypatch,
) -> None:
    memory_dir = tmp_path / "sase" / "memory"
    memory_dir.mkdir(parents=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(prompt_catalog, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(prompt_catalog, "get_xprompt_search_paths", lambda: [])
    monkeypatch.setattr(
        prompt_catalog,
        "resolve_memory_file_sources",
        lambda **_kwargs: (
            SimpleNamespace(
                paths=SimpleNamespace(candidates=(memory_dir,)),
            ),
        ),
    )

    paths = prompt_catalog.prompt_source_watch_paths([None])

    assert memory_dir in paths


def test_build_prompt_catalog_snapshot_short_circuits_unchanged_token(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        prompt_catalog,
        "_prompt_source_token",
        lambda _projects: ("same",),
    )

    assert (
        prompt_catalog.build_prompt_catalog_snapshot(
            generation=1,
            projects=[None],
            previous_source_token=("same",),
        )
        is None
    )


def test_build_prompt_catalog_snapshot_merges_xprompt_and_user_snippets(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        prompt_catalog,
        "_prompt_source_token",
        lambda _projects: ("changed",),
    )
    monkeypatch.setattr(
        prompt_catalog,
        "get_all_xprompts",
        lambda project=None: {
            "review": XPrompt(
                name="review",
                content="Review this",
                snippet=True,
            )
        },
    )
    monkeypatch.setattr(
        prompt_catalog,
        "build_xprompt_assist_entries",
        lambda project=None: [_entry("review")],
    )

    import sase.config

    monkeypatch.setattr(
        sase.config,
        "load_merged_config",
        lambda: {"ace": {"snippets": {"user": "User body$0"}}},
    )

    snapshot = prompt_catalog.build_prompt_catalog_snapshot(
        generation=2,
        projects=[None],
        previous_source_token=None,
        pending_snippet_saves={
            "combo": "#[review] + #[user]",
            "capital_ref": "#[Review]!",
        },
    )

    assert snapshot is not None
    assert snapshot.generation == 2
    assert snapshot.snippets == {
        "Combo": "Review this + User body$0",
        "Capital_ref": "Review this!$0",
        "Review": "Review this$0",
        "User": "User body$0",
        "capital_ref": "Review this!$0",
        "review": "Review this$0",
        "user": "User body$0",
        "combo": "Review this + User body$0",
    }
    assert snapshot.explicit_snippets == {
        "review": "Review this$0",
        "user": "User body$0",
        "combo": "#[review] + #[user]",
        "capital_ref": "#[Review]!",
    }
    assert snapshot.user_snippets == {"user": "User body$0"}
    assert snapshot.assist_entries_by_project[None][0].name == "review"


def test_prompt_catalog_preserves_explicit_capitalized_collisions(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        prompt_catalog,
        "_prompt_source_token",
        lambda _projects: ("changed",),
    )
    monkeypatch.setattr(
        prompt_catalog,
        "get_all_xprompts",
        lambda project=None: {
            "foo": XPrompt(name="foo", content="xprompt lower", snippet=True),
            "Foo": XPrompt(name="Foo", content="xprompt capital", snippet=True),
            "bar": XPrompt(name="bar", content="xprompt bar", snippet=True),
        },
    )
    monkeypatch.setattr(
        prompt_catalog,
        "build_xprompt_assist_entries",
        lambda project=None: [],
    )

    import sase.config

    monkeypatch.setattr(
        sase.config,
        "load_merged_config",
        lambda: {
            "ace": {
                "snippets": {
                    "foo": "user lower",
                    "Bar": "user capital",
                    "User_only": "authored capital",
                    "user_only": "user lowercase",
                }
            }
        },
    )

    snapshot = prompt_catalog.build_prompt_catalog_snapshot(
        generation=1,
        projects=[None],
    )

    assert snapshot is not None
    assert snapshot.explicit_snippets == {
        "foo": "user lower",
        "Foo": "xprompt capital$0",
        "bar": "xprompt bar$0",
        "Bar": "user capital",
        "User_only": "authored capital",
        "user_only": "user lowercase",
    }
    assert snapshot.snippets["foo"] == "user lower"
    assert snapshot.snippets["Foo"] == "xprompt capital$0"
    assert snapshot.snippets["bar"] == "xprompt bar$0"
    assert snapshot.snippets["Bar"] == "user capital"
    assert snapshot.snippets["user_only"] == "user lowercase"
    assert snapshot.snippets["User_only"] == "authored capital"
    assert snapshot.user_snippets == {
        "foo": "user lower",
        "Bar": "user capital",
        "User_only": "authored capital",
        "user_only": "user lowercase",
    }


def test_config_dirty_build_invalidates_warm_merged_config(monkeypatch) -> None:
    state = {"fresh": False}
    monkeypatch.setattr(
        prompt_catalog,
        "_prompt_source_token",
        lambda _projects: ("fresh",) if state["fresh"] else ("stale",),
    )
    monkeypatch.setattr(prompt_catalog, "get_all_xprompts", lambda project=None: {})
    monkeypatch.setattr(
        prompt_catalog,
        "build_xprompt_assist_entries",
        lambda project=None: [],
    )

    import sase.config
    from sase.config import core as config_core

    monkeypatch.setattr(
        config_core,
        "clear_config_cache",
        lambda: state.__setitem__("fresh", True),
    )
    monkeypatch.setattr(
        sase.config,
        "load_merged_config",
        lambda: {
            "ace": {
                "snippets": {
                    "saved": "new" if state["fresh"] else "old",
                }
            }
        },
    )

    snapshot = prompt_catalog.build_prompt_catalog_snapshot(
        generation=3,
        projects=[None],
        previous_source_token=("stale",),
        config_dirty=True,
    )

    assert snapshot is not None
    assert snapshot.user_snippets == {"saved": "new"}
    assert snapshot.explicit_snippets == {"saved": "new"}
    assert snapshot.snippets == {"Saved": "New", "saved": "new"}


def test_compose_pending_snippet_saves_preserves_existing_and_resolves_refs() -> None:
    composed = prompt_catalog.compose_pending_snippet_saves(
        {"xprompt": "Existing $1$0", "user": "User"},
        {"saved": "#[xprompt] then $1"},
    )

    assert composed["xprompt"] == "Existing $1$0"
    assert composed["Xprompt"] == "Existing $1$0"
    assert composed["user"] == "User"
    assert composed["User"] == "User"
    assert composed["saved"] == "Existing $1 then $2$0"
    assert composed["Saved"] == "Existing $1 then $2$0"


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
        assist_entries_by_project={None: (_entry("review"),)},
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
        assist_entries_by_project={None: (_entry("ship"),)},
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
        assist_entries_by_project={None: (_entry("global"),)},
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
