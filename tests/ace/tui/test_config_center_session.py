"""Session-only Admin Center entry bookmark coverage."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState


def test_direct_config_center_modals_get_independent_session_state() -> None:
    first = ConfigCenterModal()
    second = ConfigCenterModal()

    assert first._session_state is not second._session_state

    first._session_state.tasks.task.record("task-a", 2)

    assert second._session_state.tasks.task.identity is None
    assert second._session_state.tasks.task.row is None


async def test_ace_app_reuses_one_session_state_across_modals() -> None:
    async with AcePage(initial_tab="agents") as page:
        state = page.app._admin_center_session_state
        assert isinstance(state, AdminCenterSessionState)

        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        first = page.app.screen
        assert isinstance(first, ConfigCenterModal)
        assert first._session_state is state

        await page.press("escape")
        await page.expect_no_modal()
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        second = page.app.screen
        assert isinstance(second, ConfigCenterModal)
        assert second._session_state is state


async def test_home_only_open_does_not_create_panes_or_mutate_bookmarks() -> None:
    async with AcePage(initial_tab="agents") as page:
        state = page.app._admin_center_session_state
        state.tasks.task.record("task-a", 3)

        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        assert modal._panes == {}

        await page.press("escape")
        await page.expect_no_modal()

        assert state.tasks.task.identity == "task-a"
        assert state.tasks.task.row == 3


async def test_distinct_ace_apps_do_not_share_session_state() -> None:
    async with AcePage(initial_tab="agents") as first_page:
        first_state = first_page.app._admin_center_session_state

    async with AcePage(initial_tab="agents") as second_page:
        second_state = second_page.app._admin_center_session_state

    assert first_state is not second_state
