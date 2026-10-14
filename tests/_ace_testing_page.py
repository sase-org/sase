"""Basic AcePage behavior tests."""

import pytest

from sase.ace.testing import AcePage, make_patch


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
        await page.press(page.artifacts_digit("patches"))
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


async def test_wait_for_custom_timeout_message() -> None:
    """wait_for includes a caller-supplied timeout message."""
    async with AcePage() as page:
        with pytest.raises(AssertionError, match="archive-expand-timeout"):
            await page.wait_for(
                lambda _state: False,
                timeout=0.05,
                timeout_message=lambda: "archive-expand-timeout",
            )


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
        assert app._stall_watchdog is None
        assert app._agents_refresh_pending_callbacks == []
        assert app._agents_with_children == []
        assert page.state["total"] == 3
        assert not any(
            task.get_name() == "sase-artifacts-project-choices" and not task.done()
            for task in app._pump_free_async_tasks
        )

    assert app._fs_watcher is None
    assert app._prompt_source_watcher is None
    assert app._stall_watchdog is None
    assert not app._pump_free_async_tasks
    assert all(worker.is_finished for worker in app.workers)
