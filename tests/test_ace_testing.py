"""Tests for the ace testing DSL (AcePage, PromptPage)."""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.css.stylesheet import Stylesheet

import sase.ace.patch as patch_module
import sase.ace.testing as testing_module
from sase.ace.testing import (
    ACE_PAGE_GROUP_ISOLATION_ENV,
    AcePage,
    AcePageGroup,
    PromptPage,
    clear_fast_stylesheet_cache,
    fast_stylesheet_cache_stats,
    make_changespec as make_patch,  # legacy ACE test helper name
)
from sase.ace.tui import AceApp


async def test_ace_page_initial_state() -> None:
    """AcePage returns expected state dict after entering context."""
    async with AcePage() as page:
        state = page.state
        assert state["idx"] == 0
        assert state["total"] == 3
        assert state["tab"] == "artifacts"
        assert state["modal"] is None
        assert state["selected"]["name"] == "feature_a"


async def test_ace_page_press() -> None:
    """Pressing 'j' changes the current index."""
    async with AcePage() as page:
        assert page.state["idx"] == 0
        await page.press("2")
        await page.press("j")
        assert page.state["idx"] == 1


async def test_ace_page_screen() -> None:
    """Screen property returns non-empty string."""
    async with AcePage() as page:
        screen = page.screen
        assert isinstance(screen, str)
        assert len(screen) > 0


async def test_ace_page_export_svg() -> None:
    """export_svg returns a Textual SVG screenshot."""
    async with AcePage() as page:
        svg = page.export_svg(title="ACE Test")
        assert isinstance(svg, str)
        assert "<svg" in svg
        assert "rich-terminal" in svg


async def test_ace_page_custom_patches() -> None:
    """Passing custom patches overrides defaults."""
    custom = [
        make_patch(name="custom_a"),
        make_patch(name="custom_b"),
    ]
    async with AcePage(query='"custom"', patches=custom) as page:
        state = page.state
        assert state["total"] == 2
        assert state["selected"]["name"] == "custom_a"


async def test_expect_state_passes() -> None:
    """expect_state succeeds when the value matches immediately."""
    async with AcePage() as page:
        await page.expect_state("idx", 0)
        await page.expect_state("total", 3)
        await page.expect_state("tab", "artifacts")


async def test_expect_state_fails_on_timeout() -> None:
    """expect_state raises AssertionError when the value never matches."""
    async with AcePage() as page:
        with pytest.raises(AssertionError, match="expect_state.*timed out"):
            await page.expect_state("idx", 999, timeout=0.1)


async def test_expect_state_timeout_preserves_last_value_message() -> None:
    async with AcePage() as page:
        with pytest.raises(AssertionError) as excinfo:
            await page.expect_state("idx", 999, timeout=0)

    assert (
        str(excinfo.value)
        == "expect_state('idx', 999) timed out after 0s — last value was 0"
    )


async def test_expect_state_nested_key() -> None:
    """Dot-notation like 'selected.name' resolves nested dict keys."""
    async with AcePage() as page:
        await page.expect_state("selected.name", "feature_a")


async def test_expect_modal() -> None:
    """expect_modal succeeds after opening a modal."""
    async with AcePage() as page:
        await page.press("?")
        await page.expect_modal("HelpModal")


async def test_expect_no_modal() -> None:
    """expect_no_modal succeeds when no modal is shown."""
    async with AcePage() as page:
        await page.expect_no_modal()


async def test_expect_screen_contains() -> None:
    """expect_screen_contains succeeds when text is present in screen output."""
    async with AcePage() as page:
        # Screen in headless test mode is whitespace; verify the polling
        # mechanism works by checking for a character that IS present.
        await page.expect_screen_contains(" ")


async def test_expect_screen_contains_timeout() -> None:
    """expect_screen_contains raises AssertionError when text is never found."""
    async with AcePage() as page:
        with pytest.raises(AssertionError, match="expect_screen_contains.*timed out"):
            await page.expect_screen_contains("nonexistent_xyz", timeout=0.1)


async def test_expect_screen_not_contains() -> None:
    """expect_screen_not_contains succeeds when text is absent."""
    async with AcePage() as page:
        await page.expect_screen_not_contains("nonexistent_xyz")


async def test_wait_for() -> None:
    """wait_for succeeds with a custom predicate."""
    async with AcePage() as page:
        await page.wait_for(lambda state: state["total"] > 0)


async def test_ace_page_fast_startup_is_structurally_quiet() -> None:
    """Default pages mount real widgets without owning background services."""
    async with AcePage() as page:
        app = page.app
        assert app.animation_level == "none"
        assert app._mount_state_loads_done is True
        assert app._agents_first_load_done is True
        assert app._axe_first_load_done is True
        assert app._fs_watcher is None
        assert app._prompt_source_watcher is None
        assert app._prompt_catalog is None
        assert app._automatic_update_check_timer is None
        assert app._agents_sync_check_timer is None
        assert app._stall_watchdog is None
        assert app._agents_refresh_pending_callbacks == []
        assert app._agents_with_children == []
        assert page.state["total"] == 3

    assert app._fs_watcher is None
    assert app._prompt_source_watcher is None
    assert app._stall_watchdog is None
    assert not app._pump_free_async_tasks
    assert all(worker.is_finished for worker in app.workers)


async def test_ace_page_real_startup_policy_invokes_production_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifecycle tests can explicitly opt back into every startup boundary."""
    calls: set[str] = set()

    async def mount_state(app: AceApp) -> None:
        calls.add("mount-state")
        app._apply_patches(app._read_patches_from_disk())
        app._mount_state_loads_done = True

    async def agents(app: AceApp) -> None:
        calls.add("agents")
        app._agents_first_load_done = True

    async def axe(app: AceApp) -> None:
        calls.add("axe")
        app._axe_first_load_done = True

    def record(name: str) -> Callable[..., None]:
        def callback(*_args: object, **_kwargs: object) -> None:
            calls.add(name)

        return callback

    monkeypatch.setattr(AceApp, "_run_mount_state_loads", mount_state)
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
        "_schedule_startup_agents_sync_check",
        record("agents-sync-check"),
    )
    monkeypatch.setattr(
        testing_module._stall_watchdog,
        "start_event_loop_stall_watchdog",
        record("stall-watchdog"),
    )
    clear_fast_stylesheet_cache()

    async with AcePage(startup_policy="real"):
        pass

    assert fast_stylesheet_cache_stats().misses == 0
    assert fast_stylesheet_cache_stats().hits == 0
    assert fast_stylesheet_cache_stats().stores == 0
    assert calls >= {
        "mount-state",
        "fold-state",
        "agents",
        "axe",
        "artifact-watcher",
        "prompt-watcher",
        "prompt-catalog",
        "update-check",
        "agents-sync-check",
        "stall-watchdog",
    }


async def test_ace_page_restores_fast_startup_overrides_after_success() -> None:
    originals = (
        AceApp._run_mount_state_loads,
        AceApp._run_agent_index_startup_prepare_and_refresh,
        AceApp._start_artifact_watcher,
        testing_module._stall_watchdog.start_event_loop_stall_watchdog,
    )

    async with AcePage():
        assert AceApp._run_mount_state_loads is not originals[0]
        assert AceApp._run_agent_index_startup_prepare_and_refresh is not originals[1]
        assert AceApp._start_artifact_watcher is not originals[2]
        assert (
            testing_module._stall_watchdog.start_event_loop_stall_watchdog
            is not originals[3]
        )

    assert (
        AceApp._run_mount_state_loads,
        AceApp._run_agent_index_startup_prepare_and_refresh,
        AceApp._start_artifact_watcher,
        testing_module._stall_watchdog.start_event_loop_stall_watchdog,
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

    async with AcePage():
        assert (
            testing_module._plugins_browser_pane._load_plugins_catalog
            is plugins_catalog
        )

    assert calls >= {"agents", "axe"}


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


async def test_ace_page_group_reuses_page_and_resets_prompt_without_history() -> None:
    with (
        patch("sase.config.load_merged_config", return_value={"ace": {}}),
        patch("sase.history.prompt.add_or_update_prompt") as save_history,
    ):
        async with AcePageGroup() as group:
            async with group.checkout() as page:
                app = page.app
                app._show_prompt_input_bar_for_home(initial_text="hello")
                await page.pause()
                assert app.query("#prompt-input-bar")

            async with group.checkout() as next_page:
                assert next_page.app is app
                assert not next_page.app.query("#prompt-input-bar")

    save_history.assert_not_called()


async def test_ace_page_group_rejects_overlapping_checkouts() -> None:
    async with AcePageGroup() as group:
        checkout = group.checkout()
        await checkout.__aenter__()
        try:
            with pytest.raises(RuntimeError, match="overlapping checkouts"):
                async with group.checkout():
                    pass
        finally:
            await checkout.__aexit__(None, None, None)


async def test_ace_page_group_reports_reset_hook_leaks() -> None:
    def leak(page: AcePage) -> None:
        page.app.current_idx = 1

    async with AcePageGroup(reset_hook=leak) as group:
        with pytest.raises(AssertionError, match="idx"):
            async with group.checkout():
                pass


async def test_ace_page_group_isolation_mode_creates_distinct_apps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ACE_PAGE_GROUP_ISOLATION_ENV, "1")

    async with AcePageGroup() as group:
        async with group.checkout() as first:
            first_app = first.app
        async with group.checkout() as second:
            assert second.app is not first_app


@pytest.mark.parametrize("failure_phase", ["construction", "mount"])
async def test_ace_page_restores_overrides_when_entry_fails(
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
) -> None:
    original_mount_state = AceApp._run_mount_state_loads
    original_find = patch_module.find_all_patches

    if failure_phase == "construction":

        def fail_init(self: AceApp, *_args: object, **_kwargs: object) -> None:
            del self
            raise RuntimeError("construction failed")

        monkeypatch.setattr(AceApp, "__init__", fail_init)
    else:

        class FailingPilotContext:
            async def __aenter__(self) -> None:
                raise RuntimeError("mount failed")

            async def __aexit__(
                self,
                _exc_type: object,
                _exc_val: object,
                _exc_tb: object,
            ) -> None:
                return None

        monkeypatch.setattr(
            AceApp,
            "run_test",
            lambda *_args, **_kwargs: FailingPilotContext(),
        )

    page = AcePage()
    with pytest.raises(RuntimeError, match=f"{failure_phase} failed"):
        await page.__aenter__()

    assert AceApp._run_mount_state_loads is original_mount_state
    assert patch_module.find_all_patches is original_find


def test_ace_page_rejects_unknown_startup_policy() -> None:
    with pytest.raises(ValueError, match="unsupported AcePage startup policy"):
        AcePage(startup_policy="unknown")  # type: ignore[arg-type]


# =============================================================================
# PromptPage tests
# =============================================================================


async def test_prompt_page_initial_state() -> None:
    """PromptPage sets text, cursor, and mode on entry."""
    async with PromptPage("hello world", cursor=(0, 5)) as page:
        assert page.text == "hello world"
        assert page.cursor == (0, 5)
        assert page.mode == "normal"


async def test_prompt_page_press() -> None:
    """Pressing keys through PromptPage works."""
    async with PromptPage("one two three", cursor=(0, 0)) as page:
        await page.press("d", "w")
        assert page.text == "two three"


async def test_prompt_page_insert_mode() -> None:
    """PromptPage with mode='insert' does not enter normal mode."""
    async with PromptPage("hello", mode="insert") as page:
        assert page.mode == "insert"


async def test_prompt_page_ta_access() -> None:
    """page.ta gives direct access to the PromptTextArea widget."""
    async with PromptPage("test") as page:
        assert page.ta.text == "test"
        assert page.ta._vim_mode == "normal"


async def test_prompt_page_cursor_setter() -> None:
    """page.cursor can be set mid-test."""
    async with PromptPage("hello\nworld", cursor=(0, 0)) as page:
        page.cursor = (1, 3)
        assert page.cursor == (1, 3)
