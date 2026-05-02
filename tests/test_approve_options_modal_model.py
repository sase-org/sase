"""Coder-model tests for the approve-options modal."""

from textual.widgets import Static, Switch

from sase.ace.tui.modals.approve_options_modal import (
    ApproveOptionsEditPrompt,
    ApproveOptionsModal,
    ApproveOptionsResult,
)

from ._approve_options_modal_helpers import ApproveOptionsApp


async def test_m_key_no_op_when_coder_off() -> None:
    """Pressing 'm' when coder is OFF should not push a modal."""
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        # Turn coder OFF
        coder_sw = modal.query_one("#run-coder-switch", Switch)
        coder_sw.focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert not coder_sw.value

        # Count screens before pressing m
        screen_count_before = len(pilot.app.screen_stack)

        await pilot.press("m")
        await pilot.pause()

        # No new screen should have been pushed
        assert len(pilot.app.screen_stack) == screen_count_before


async def test_model_persists_through_approve() -> None:
    """coder_model should be included in ApproveOptionsResult."""
    result: ApproveOptionsResult | ApproveOptionsEditPrompt | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(
            r: ApproveOptionsResult | ApproveOptionsEditPrompt | None,
        ) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal(coder_model="opus")
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsResult)
        assert result.coder_model == "opus"


async def test_model_persists_through_edit_prompt() -> None:
    """coder_model should be included in ApproveOptionsEditPrompt."""
    result: ApproveOptionsResult | ApproveOptionsEditPrompt | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(
            r: ApproveOptionsResult | ApproveOptionsEditPrompt | None,
        ) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal(coder_model="codex/o3")
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("p")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsEditPrompt)
        assert result.coder_model == "codex/o3"


async def test_initial_model_restoration() -> None:
    """Constructor coder_model param should restore model display."""
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal(coder_model="opus")
        pilot.app.push_screen(modal)
        await pilot.pause()

        model_display = modal.query_one("#coder-model-display", Static)
        display_text = str(model_display.render())
        assert "CLAUDE(opus)" in display_text


async def test_default_model_shows_same_as_planner() -> None:
    """No coder_model should display 'Same as planner'."""
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        model_display = modal.query_one("#coder-model-display", Static)
        display_text = str(model_display.render())
        assert "Same as planner" in display_text


async def test_approve_with_no_model_returns_none() -> None:
    """Approving without setting a model should return coder_model=None."""
    result: ApproveOptionsResult | ApproveOptionsEditPrompt | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(
            r: ApproveOptionsResult | ApproveOptionsEditPrompt | None,
        ) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsResult)
        assert result.coder_model is None
