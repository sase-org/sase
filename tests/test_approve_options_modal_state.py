"""Switch and prompt-state tests for the approve-options modal."""

from textual.widgets import Static, Switch

from sase.ace.tui.modals.approve_options_modal import (
    ApproveOptionsEditPrompt,
    ApproveOptionsModal,
    ApproveOptionsResult,
)

from ._approve_options_modal_helpers import ApproveOptionsApp


async def test_toggle_coder_off_locks_commit_on() -> None:
    """Turning off coder locks commit switch (at least one must be ON)."""
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        commit_sw = modal.query_one("#commit-plan-switch", Switch)
        coder_sw = modal.query_one("#run-coder-switch", Switch)
        commit_lbl = modal.query_one("#commit-plan-label", Static)

        # Toggle coder OFF via space on the switch
        coder_sw.focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

        assert not coder_sw.value
        assert commit_sw.value is True
        assert commit_sw.disabled is True
        assert "locked" in commit_lbl.classes
        assert "(required)" in str(commit_lbl.render())


async def test_toggle_commit_off_locks_coder_on() -> None:
    """Turning off commit locks coder switch (at least one must be ON)."""
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        commit_sw = modal.query_one("#commit-plan-switch", Switch)
        coder_sw = modal.query_one("#run-coder-switch", Switch)
        coder_lbl = modal.query_one("#run-coder-label", Static)

        # Toggle commit OFF
        commit_sw.focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

        assert not commit_sw.value
        assert coder_sw.value is True
        assert coder_sw.disabled is True
        assert "locked" in coder_lbl.classes
        assert "(required)" in str(coder_lbl.render())


async def test_toggle_back_on_unlocks_other() -> None:
    """Toggling a switch back ON re-enables the other switch."""
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        commit_sw = modal.query_one("#commit-plan-switch", Switch)
        coder_sw = modal.query_one("#run-coder-switch", Switch)

        # Toggle coder OFF, then back ON
        coder_sw.focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

        assert commit_sw.disabled is False
        assert coder_sw.disabled is False
        assert coder_sw.value is True


async def test_coder_off_disables_prompt_display() -> None:
    """When coder is OFF, prompt and model displays should be disabled."""
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        coder_sw = modal.query_one("#run-coder-switch", Switch)
        prompt_display = modal.query_one("#coder-prompt-display", Static)
        model_display = modal.query_one("#coder-model-display", Static)

        coder_sw.focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

        assert "disabled" in prompt_display.classes
        assert "disabled" in model_display.classes


async def test_p_key_triggers_edit_prompt() -> None:
    """Pressing 'p' should dismiss with ApproveOptionsEditPrompt."""
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

        await pilot.press("p")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsEditPrompt)
        assert result.run_coder is True
        assert result.commit_plan is True
        assert result.coder_prompt == ""


async def test_p_key_no_op_when_coder_off() -> None:
    """Pressing 'p' when coder is OFF should not dismiss the modal."""
    dismissed = False

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(
            _: ApproveOptionsResult | ApproveOptionsEditPrompt | None,
        ) -> None:
            nonlocal dismissed
            dismissed = True

        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # Turn coder OFF
        coder_sw = modal.query_one("#run-coder-switch", Switch)
        coder_sw.focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert not coder_sw.value

        # Press p; should be no-op
        await pilot.press("p")
        await pilot.pause()

        assert not dismissed


async def test_initial_state_restoration() -> None:
    """Constructor params should restore switch and prompt state."""
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal(
            commit_plan=False,
            run_coder=True,
            coder_prompt="do the thing",
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        commit_sw = modal.query_one("#commit-plan-switch", Switch)
        coder_sw = modal.query_one("#run-coder-switch", Switch)
        prompt_display = modal.query_one("#coder-prompt-display", Static)

        assert commit_sw.value is False
        assert coder_sw.value is True
        display_text = str(prompt_display.render())
        assert "do the thing" in display_text


async def test_p_key_preserves_state_in_edit_prompt() -> None:
    """ApproveOptionsEditPrompt should carry current switch + prompt state."""
    result: ApproveOptionsResult | ApproveOptionsEditPrompt | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(
            r: ApproveOptionsResult | ApproveOptionsEditPrompt | None,
        ) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal(
            commit_plan=False,
            run_coder=True,
            coder_prompt="existing prompt",
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("p")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsEditPrompt)
        assert result.commit_plan is False
        assert result.run_coder is True
        assert result.coder_prompt == "existing prompt"


async def test_long_prompt_truncated_in_display() -> None:
    """Long prompts should be truncated with ... in the display."""
    async with ApproveOptionsApp().run_test() as pilot:
        long_prompt = "a" * 100
        modal = ApproveOptionsModal(coder_prompt=long_prompt)
        pilot.app.push_screen(modal)
        await pilot.pause()

        prompt_display = modal.query_one("#coder-prompt-display", Static)
        display_text = str(prompt_display.render())
        assert "..." in display_text
        assert len(display_text) < len(long_prompt)


async def test_empty_prompt_shows_none() -> None:
    """Empty prompt should display 'none'."""
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        prompt_display = modal.query_one("#coder-prompt-display", Static)
        display_text = str(prompt_display.render())
        assert "none" in display_text


async def test_title_and_footer_use_tale_label() -> None:
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        title = modal.query_one("#approve-options-title", Static)
        footer = modal.query_one("#approve-options-footer", Static)

        title_text = str(title.render())
        footer_text = str(footer.render())

        assert "Tale Options" in title_text
        assert "Tale" in footer_text
        assert "Approve with Options" not in title_text
        assert "Approve" not in footer_text
