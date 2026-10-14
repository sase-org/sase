"""AcePage startup and stylesheet cache tests."""

import asyncio
from collections.abc import Callable
from pathlib import Path
import threading

import pytest
from textual.css.stylesheet import Stylesheet

import sase.ace.patch as patch_module
import sase.ace.testing as testing_module
from sase.ace.testing import (
    AcePage,
    clear_fast_stylesheet_cache,
    fast_stylesheet_cache_stats,
)
from sase.ace.tui import AceApp
from sase.ace.tui.actions import artifacts as artifacts_actions
from sase.ace.tui.proc_observer import PROC_OBSERVER_THREAD_NAME


async def test_drain_pump_free_tasks_discards_already_done_tasks() -> None:
    """The drain prunes done tasks itself instead of awaiting the callback."""
    from types import SimpleNamespace

    from sase.ace.testing.ace_page import _drain_pump_free_tasks

    async def _noop() -> None:
        return None

    # A task that is already done whose registry-discard done callback has
    # not run yet: gathering over it yields nothing on Python 3.12, so a
    # callback-only drain would leave it registered.
    task = asyncio.get_running_loop().create_task(
        _noop(), name="sase-agents-onboarding-plugins"
    )
    await task
    assert task.done()
    registry = {task}
    app = SimpleNamespace(
        _pump_free_task_registry_attrs={"_pump_free_async_tasks"},
        _pump_free_async_tasks=registry,
    )
    await _drain_pump_free_tasks(app)  # type: ignore[arg-type]
    assert registry == set()


async def test_ace_page_teardown_cancels_textual_workers() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()
    never = asyncio.Event()

    async def blocked_worker() -> None:
        started.set()
        try:
            await never.wait()
        finally:
            cancelled.set()

    async with AcePage() as page:
        worker = page.app.run_worker(
            blocked_worker(),
            name="ace-page-blocked-worker",
            exit_on_error=False,
        )
        await page.wait_for(lambda _state: started.is_set())
        assert worker.is_running

    assert worker.is_finished
    assert cancelled.is_set()


async def test_ace_page_real_startup_policy_invokes_production_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifecycle tests can explicitly opt back into every startup boundary."""
    calls: set[str] = set()

    async def notification_state(app: AceApp) -> None:
        calls.add("notification-state")
        app._mount_notification_state_load_done = True
        app._maybe_mark_mount_state_loads_done()

    async def deferred_state(app: AceApp) -> None:
        calls.add("deferred-state")
        app._apply_patches(app._read_patches_from_disk())
        app._mount_deferred_state_load_done = True
        app._maybe_mark_mount_state_loads_done()

    async def agents(app: AceApp) -> None:
        calls.add("agents")
        app._agents_first_load_done = True
        app._mark_startup_agents_ready()
        app._maybe_end_startup_stopwatch()

    async def axe(app: AceApp) -> None:
        calls.add("axe")
        app._axe_first_load_done = True
        app._mark_startup_axe_ready()
        app._maybe_end_startup_stopwatch()

    def record(name: str) -> Callable[..., None]:
        def callback(*_args: object, **_kwargs: object) -> None:
            calls.add(name)

        return callback

    monkeypatch.setattr(
        AceApp,
        "_run_mount_notification_state_loads",
        notification_state,
    )
    monkeypatch.setattr(AceApp, "_run_deferred_mount_state_loads", deferred_state)
    monkeypatch.setattr(
        AceApp,
        "_schedule_agents_fold_state_load",
        record("fold-state"),
    )
    monkeypatch.setattr(
        AceApp,
        "_run_agent_index_startup_prepare_and_refresh",
        agents,
    )
    monkeypatch.setattr(AceApp, "_run_axe_startup_init", axe)
    monkeypatch.setattr(
        AceApp,
        "_start_artifact_watcher",
        record("artifact-watcher"),
    )
    monkeypatch.setattr(
        AceApp,
        "_start_prompt_source_watcher",
        record("prompt-watcher"),
    )
    monkeypatch.setattr(
        AceApp,
        "_schedule_prompt_catalog_rebuild",
        record("prompt-catalog"),
    )
    monkeypatch.setattr(
        AceApp,
        "_schedule_startup_update_toast_check",
        record("update-check"),
    )
    monkeypatch.setattr(
        AceApp,
        "_schedule_link_index_refresh",
        record("link-index"),
    )
    monkeypatch.setattr(
        testing_module._stall_watchdog,
        "start_event_loop_stall_watchdog",
        record("stall-watchdog"),
    )
    clear_fast_stylesheet_cache()

    async with AcePage(startup_policy="real") as page:
        deadline = asyncio.get_running_loop().time() + 30.0
        while "update-check" not in calls:
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError(
                    "startup maintenance chain never recorded update-check; "
                    f"got {sorted(calls)}"
                )
            await page.pause()

    assert fast_stylesheet_cache_stats().misses == 0
    assert fast_stylesheet_cache_stats().hits == 0
    assert fast_stylesheet_cache_stats().stores == 0
    assert calls >= {
        "notification-state",
        "deferred-state",
        "fold-state",
        "agents",
        "axe",
        "artifact-watcher",
        "prompt-watcher",
        "prompt-catalog",
        "link-index",
        "update-check",
        "stall-watchdog",
    }


async def test_ace_page_restores_fast_startup_overrides_after_success() -> None:
    originals = (
        AceApp._run_mount_notification_state_loads,
        AceApp._run_deferred_mount_state_loads,
        AceApp._run_agent_index_startup_prepare_and_refresh,
        AceApp._start_artifact_watcher,
        testing_module._stall_watchdog.start_event_loop_stall_watchdog,
        artifacts_actions._collect_artifacts_project_choices,
    )

    async with AcePage():
        assert AceApp._run_mount_notification_state_loads is not originals[0]
        assert AceApp._run_deferred_mount_state_loads is not originals[1]
        assert AceApp._run_agent_index_startup_prepare_and_refresh is not originals[2]
        assert AceApp._start_artifact_watcher is not originals[3]
        assert (
            testing_module._stall_watchdog.start_event_loop_stall_watchdog
            is not originals[4]
        )
        assert artifacts_actions._collect_artifacts_project_choices is not originals[5]

    assert (
        AceApp._run_mount_notification_state_loads,
        AceApp._run_deferred_mount_state_loads,
        AceApp._run_agent_index_startup_prepare_and_refresh,
        AceApp._start_artifact_watcher,
        testing_module._stall_watchdog.start_event_loop_stall_watchdog,
        artifacts_actions._collect_artifacts_project_choices,
    ) == originals


async def test_ace_page_preserves_caller_supplied_startup_fixtures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fast startup defers to startup sources patched by the caller."""
    calls: set[str] = set()

    async def agents(app: AceApp) -> None:
        calls.add("agents")
        app._agents_first_load_done = True

    async def axe(app: AceApp) -> None:
        calls.add("axe")
        app._axe_first_load_done = True

    def plugins_catalog(**_kwargs: object) -> object:
        calls.add("plugins")
        return object()

    def collect_project_choices() -> object:
        calls.add("project-choices")
        return artifacts_actions._ArtifactsProjectChoices(
            choices=(),
            enabled_projects=(),
            display_names={},
        )

    monkeypatch.setattr(
        AceApp,
        "_run_agent_index_startup_prepare_and_refresh",
        agents,
    )
    monkeypatch.setattr(AceApp, "_run_axe_startup_init", axe)
    monkeypatch.setattr(
        testing_module._plugins_browser_pane,
        "_load_plugins_catalog",
        plugins_catalog,
    )
    monkeypatch.setattr(
        artifacts_actions,
        "_collect_artifacts_project_choices",
        collect_project_choices,
    )

    async with AcePage():
        assert (
            testing_module._plugins_browser_pane._load_plugins_catalog
            is plugins_catalog
        )
        assert (
            artifacts_actions._collect_artifacts_project_choices
            is collect_project_choices
        )

    assert calls >= {"agents", "axe", "project-choices"}


async def test_ace_page_fast_stylesheet_cache_skips_second_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_fast_stylesheet_cache()
    original_parse = Stylesheet.parse
    parse_calls = 0
    source_css = str(
        Path(__file__).resolve().parents[1] / "src/sase/ace/tui/styles.tcss"
    )

    def parse(self: Stylesheet) -> None:
        nonlocal parse_calls
        if any(str(read_from[0]) == source_css for read_from in self.source):
            parse_calls += 1
        original_parse(self)

    monkeypatch.setattr(Stylesheet, "parse", parse)

    async with AcePage():
        pass
    first_parse_calls = parse_calls
    assert first_parse_calls > 0

    page = AcePage()
    await page.__aenter__()
    try:
        assert parse_calls == first_parse_calls
    finally:
        await page.__aexit__(None, None, None)

    stats = fast_stylesheet_cache_stats()
    assert stats.hits == 1
    assert stats.misses == 1
    assert stats.stores == 1


async def test_ace_page_fast_stylesheet_cache_invalidates_changed_css_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    clear_fast_stylesheet_cache()
    repo_root = Path(__file__).resolve().parents[1]
    source_css = repo_root / "src/sase/ace/tui/styles.tcss"
    css_path = tmp_path / "styles.tcss"
    css_text = source_css.read_text(encoding="utf-8")
    css_path.write_text(css_text, encoding="utf-8")
    monkeypatch.setattr(AceApp, "CSS_PATH", css_path)

    async with AcePage():
        pass
    css_path.write_text(css_text + "\n/* cache invalidation */\n", encoding="utf-8")
    async with AcePage():
        pass

    stats = fast_stylesheet_cache_stats()
    assert stats.hits == 0
    assert stats.misses == 2
    assert stats.stores == 2


def _css_dimensions(page: AcePage) -> dict[str, tuple[str, str]]:
    """Read stylesheet-driven width/height for a few always-present widgets."""
    return {
        selector: (
            str(page.app.query_one(selector).styles.width),
            str(page.app.query_one(selector).styles.height),
        )
        for selector in ("#artifacts-view", "#detail-scroll")
    }


async def test_ace_page_fast_stylesheet_cache_still_applies_rules() -> None:
    """A cache hit must apply the same CSS a freshly parsed stylesheet does."""
    clear_fast_stylesheet_cache()
    async with AcePage() as page:
        parsed_dimensions = _css_dimensions(page)
    assert all("None" not in dimensions for dimensions in parsed_dimensions.values()), (
        parsed_dimensions
    )

    async with AcePage() as page:
        assert fast_stylesheet_cache_stats().hits == 1
        assert _css_dimensions(page) == parsed_dimensions
        # ``RuleSet`` hashes by identity and ``Stylesheet.apply`` filters
        # ``rules`` by membership in a set built from ``rules_map``, so a
        # hydrated stylesheet whose two halves are distinct copies applies no
        # rules at all while still looking well populated.
        stylesheet = page.app.stylesheet
        indexed = {
            id(rule) for entry in stylesheet.rules_map.values() for rule in entry
        }
        assert indexed and indexed <= {id(rule) for rule in stylesheet.rules}


async def test_ace_page_fast_stylesheet_cache_hydrates_mutable_data_per_app() -> None:
    clear_fast_stylesheet_cache()
    async with AcePage():
        pass

    async with AcePage() as page:
        source_count = len(page.app.stylesheet.source)
        assert source_count > 0
        assert page.app.stylesheet.rules
        page.app.stylesheet.source.clear()
        page.app.stylesheet._rules.clear()
        page.app.stylesheet._rules_map = {}

    async with AcePage() as page:
        assert len(page.app.stylesheet.source) == source_count
        assert page.app.stylesheet.rules
        assert page.app.stylesheet.rules_map
