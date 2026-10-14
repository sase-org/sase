"""AcePageGroup lifecycle and isolation tests."""

import threading
from unittest.mock import patch

import pytest

import sase.ace.patch as patch_module
from sase.ace.testing import ACE_PAGE_GROUP_ISOLATION_ENV, AcePage, AcePageGroup
from sase.ace.tui import AceApp
from sase.ace.tui.proc_observer import PROC_OBSERVER_THREAD_NAME


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


async def test_ace_page_group_clears_disabled_notifications_between_checkouts() -> None:
    async with AcePageGroup(notifications=False) as group:
        async with group.checkout() as page:
            app = page.app
            app.notify("late startup notification")
            await page.wait_for(lambda _state: len(app._notifications) > 0)

        async with group.checkout() as next_page:
            assert next_page.app is app
            assert not next_page.app._notifications


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
    original_notification_state = AceApp._run_mount_notification_state_loads
    original_deferred_state = AceApp._run_deferred_mount_state_loads
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

    assert AceApp._run_mount_notification_state_loads is original_notification_state
    assert AceApp._run_deferred_mount_state_loads is original_deferred_state
    assert patch_module.find_all_patches is original_find
    assert not any(
        thread.name == PROC_OBSERVER_THREAD_NAME and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_ace_page_rejects_unknown_startup_policy() -> None:
    with pytest.raises(ValueError, match="unsupported AcePage startup policy"):
        AcePage(startup_policy="unknown")  # type: ignore[arg-type]
