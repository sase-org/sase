"""Follow-epics toggle tests for the wait modal."""

from __future__ import annotations

from textual.widgets import Input, Static

from sase.ace.tui.modals.wait_modal import WaitModal, WaitModalResult
from tests.ace.tui._wait_modal_helpers import WaitModalTestApp as _TestApp


async def test_follow_toggle_prefills_on_off_mixed() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal(
            current_waiting_for=["planner"],
            current_wait_for_epics_of=["planner"],
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        label = modal.query_one("#follow-epics-toggle", Static)
        assert "on" in label.render().plain
        assert "↪" in label.render().plain

    async with _TestApp().run_test() as pilot:
        modal = WaitModal(current_waiting_for=["planner"])
        pilot.app.push_screen(modal)
        await pilot.pause()
        label = modal.query_one("#follow-epics-toggle", Static)
        assert label.render().plain == "Follow epics: off"

    async with _TestApp().run_test() as pilot:
        modal = WaitModal(
            current_waiting_for=["a", "b"],
            current_wait_for_epics_of=["a"],
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        assert modal._follow_mode == "mixed"
        label = modal.query_one("#follow-epics-toggle", Static)
        assert "mixed" in label.render().plain


async def test_follow_toggle_space_cycles_modes() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal(current_waiting_for=["planner"])
        pilot.app.push_screen(modal)
        await pilot.pause()
        assert modal._follow_mode == "off"

        modal.query_one("#follow-epics-toggle", Static).focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert modal._follow_mode == "mixed"
        await pilot.press("space")
        await pilot.pause()
        assert modal._follow_mode == "on"
        await pilot.press("space")
        await pilot.pause()
        assert modal._follow_mode == "off"


async def test_follow_toggle_ctrl_j_reaches_toggle() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert modal.query_one("#agents-input", Input).has_focus
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert modal.query_one("#follow-epics-toggle", Static).has_focus
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert modal.query_one("#beads-input", Input).has_focus


async def test_follow_toggle_disabled_for_plan_rows() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal(current_waiting_for=["planner--plan"])
        pilot.app.push_screen(modal)
        await pilot.pause()
        reason = modal._follow_disabled_reason()
        assert reason is not None
        before = modal._follow_mode
        modal.query_one("#follow-epics-toggle", Static).focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert modal._follow_mode == before


async def test_follow_apply_carries_epic_follow_agents() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(
            current_waiting_for=["planner", "coder"],
            current_wait_for_epics_of=["planner"],
        )
        assert modal._follow_mode == "mixed"
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert result is not None
    assert result.follow_mode == "mixed"
    assert result.epic_follow_agents == ("planner",)


async def test_follow_apply_on_arms_every_agent() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(current_waiting_for=["planner", "coder"])
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        modal._follow_mode = "on"
        await pilot.press("enter")
        await pilot.pause()

    assert result is not None
    assert result.follow_mode == "on"
    assert result.epic_follow_agents == ("planner", "coder")
