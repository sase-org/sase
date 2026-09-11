"""Choice and prompt-state tests for the custom approval modal."""

from textual.widgets import Static

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.modals.approve_options_modal import (
    ApproveOptionsEditPrompt,
    ApproveOptionsModal,
    ApproveOptionsResult,
    _CapacityInputModal,
    _CapacityInputResult,
    _WaitSpecInputModal,
    _WaitSpecInputResult,
)

from ._approve_options_modal_helpers import ApproveOptionsApp


async def test_default_choice_is_tale() -> None:
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        row = modal.query_one("#approval-choice-tale", Static)

        assert "selected" in row.classes
        assert "sdd/plans (tier: tale)" in str(row.render())


async def test_constructor_restores_explicit_choice() -> None:
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal(choice="epic", coder_prompt="do the thing")
        pilot.app.push_screen(modal)
        await pilot.pause()

        epic_row = modal.query_one("#approval-choice-epic", Static)
        prompt_display = modal.query_one("#coder-prompt-display", Static)

        assert "selected" in epic_row.classes
        assert "sdd/plans (tier: epic)" in str(epic_row.render())
        assert "do the thing" in str(prompt_display.render())


async def test_legacy_no_commit_state_maps_to_approve_choice() -> None:
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal(commit_plan=False, run_coder=True)
        pilot.app.push_screen(modal)
        await pilot.pause()

        row = modal.query_one("#approval-choice-approve", Static)

        assert "selected" in row.classes
        assert "No SDD commit" in str(row.render())


async def test_action_keys_select_choices() -> None:
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("a")
        await pilot.pause()
        assert "selected" in modal.query_one("#approval-choice-approve", Static).classes

        await pilot.press("e")
        await pilot.pause()
        assert "selected" in modal.query_one("#approval-choice-epic", Static).classes


async def test_enter_returns_selected_choice() -> None:
    result: ApproveOptionsResult | ApproveOptionsEditPrompt | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(
            r: ApproveOptionsResult | ApproveOptionsEditPrompt | None,
        ) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal(choice="approve")
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsResult)
        assert result.choice == "approve"
        assert result.commit_plan is False
        assert result.run_coder is True


async def test_wait_spec_display_and_result_are_canonical() -> None:
    result: ApproveOptionsResult | ApproveOptionsEditPrompt | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(
            r: ApproveOptionsResult | ApproveOptionsEditPrompt | None,
        ) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal(
            choice="approve",
            wait_spec="sase-s7.2, bead=sase-64.3",
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        wait_display = modal.query_one("#approval-wait-display", Static)
        assert "sase-s7.2,bead=sase-64.3" in str(wait_display.render())

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsResult)
        assert result.wait_spec == "sase-s7.2,bead=sase-64.3"


async def test_w_key_sets_wait_spec() -> None:
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("w")
        await pilot.pause()
        wait_modal = pilot.app.screen
        assert isinstance(wait_modal, _WaitSpecInputModal)
        input_widget = wait_modal.query_one(
            "#approve-wait-input",
            SingleLineVimTextArea,
        )
        input_widget.text = "sase-a.1, bead=sase-vs.4"
        input_widget.cursor_location = input_widget.document.end

        await pilot.press("enter")
        await pilot.pause()

        wait_display = modal.query_one("#approval-wait-display", Static)
        assert "sase-a.1,bead=sase-vs.4" in str(wait_display.render())


async def test_wait_spec_editor_blank_clears_value() -> None:
    result: _WaitSpecInputResult | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(r: _WaitSpecInputResult | None) -> None:
            nonlocal result
            result = r

        modal = _WaitSpecInputModal("sase-a.1")
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        input_widget = modal.query_one("#approve-wait-input", SingleLineVimTextArea)
        input_widget.text = ""

        await pilot.press("enter")
        await pilot.pause()

        assert result == _WaitSpecInputResult(None)


async def test_wait_spec_editor_rejects_invalid_value() -> None:
    result: _WaitSpecInputResult | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(r: _WaitSpecInputResult | None) -> None:
            nonlocal result
            result = r

        modal = _WaitSpecInputModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        input_widget = modal.query_one("#approve-wait-input", SingleLineVimTextArea)
        input_widget.text = "time=5m"
        input_widget.cursor_location = input_widget.document.end

        await pilot.press("enter")
        await pilot.pause()

        assert result is None
        assert isinstance(pilot.app.screen, _WaitSpecInputModal)
        error = modal.query_one("#approve-wait-error", Static)
        assert "does not accept time=" in str(error.render())


async def test_p_key_preserves_choice_in_edit_prompt() -> None:
    result: ApproveOptionsResult | ApproveOptionsEditPrompt | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(
            r: ApproveOptionsResult | ApproveOptionsEditPrompt | None,
        ) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal(
            choice="epic",
            coder_prompt="existing prompt",
            wait_spec="sase-a.1",
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("p")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsEditPrompt)
        assert result.choice == "epic"
        assert result.commit_plan is True
        assert result.run_coder is True
        assert result.coder_prompt == "existing prompt"
        assert result.wait_spec == "sase-a.1"


async def test_long_prompt_truncated_in_display() -> None:
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
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        prompt_display = modal.query_one("#coder-prompt-display", Static)
        display_text = str(prompt_display.render())
        assert "none" in display_text


async def test_title_and_footer_use_custom_label() -> None:
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        title = modal.query_one("#approve-options-title", Static)
        footer = modal.query_one("#approve-options-footer", Static)

        title_text = str(title.render())
        footer_text = str(footer.render())

        assert "Custom Approval" in title_text
        assert "a/t/e" in footer_text
        assert "Capacity" in footer_text
        assert "Tale Options" not in title_text


async def test_capacity_defaults_to_na_for_tale_and_default_for_epic() -> None:
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal(choice="tale")
        pilot.app.push_screen(modal)
        await pilot.pause()

        display = modal.query_one("#approval-capacity-display", Static)
        assert "n/a (epic only)" in str(display.render())
        assert display.has_class("disabled")

        await pilot.press("e")
        await pilot.pause()
        assert "Default" in str(display.render())
        assert not display.has_class("disabled")


async def test_capacity_zero_displays_drain_and_is_submitted_for_epic() -> None:
    result: ApproveOptionsResult | ApproveOptionsEditPrompt | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(
            r: ApproveOptionsResult | ApproveOptionsEditPrompt | None,
        ) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal(choice="epic", capacity=0)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        display = modal.query_one("#approval-capacity-display", Static)
        assert "0 (drain)" in str(display.render())

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsResult)
        assert result.choice == "epic"
        assert result.capacity == 0


async def test_c_key_sets_capacity_on_epic() -> None:
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal(choice="epic")
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()
        capacity_modal = pilot.app.screen
        assert isinstance(capacity_modal, _CapacityInputModal)
        input_widget = capacity_modal.query_one(
            "#approve-capacity-input",
            SingleLineVimTextArea,
        )
        input_widget.text = "3"
        input_widget.cursor_location = input_widget.document.end

        await pilot.press("enter")
        await pilot.pause()

        display = modal.query_one("#approval-capacity-display", Static)
        assert "3" in str(display.render())
        assert modal._capacity == 3


async def test_capacity_editor_blank_clears_value() -> None:
    result: _CapacityInputResult | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(r: _CapacityInputResult | None) -> None:
            nonlocal result
            result = r

        modal = _CapacityInputModal(3)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        input_widget = modal.query_one("#approve-capacity-input", SingleLineVimTextArea)
        input_widget.text = ""

        await pilot.press("enter")
        await pilot.pause()

        assert result == _CapacityInputResult(None)


async def test_capacity_editor_rejects_invalid_value() -> None:
    result: _CapacityInputResult | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(r: _CapacityInputResult | None) -> None:
            nonlocal result
            result = r

        modal = _CapacityInputModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        input_widget = modal.query_one("#approve-capacity-input", SingleLineVimTextArea)
        input_widget.text = "-1"
        input_widget.cursor_location = input_widget.document.end

        await pilot.press("enter")
        await pilot.pause()

        assert result is None
        assert isinstance(pilot.app.screen, _CapacityInputModal)
        error = modal.query_one("#approve-capacity-error", Static)
        assert str(error.render())


async def test_capacity_editor_cancel_keeps_previous_value() -> None:
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal(choice="epic", capacity=3)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert modal._capacity == 3
        display = modal.query_one("#approval-capacity-display", Static)
        assert "3" in str(display.render())


async def test_switching_to_tale_does_not_submit_stale_capacity() -> None:
    result: ApproveOptionsResult | ApproveOptionsEditPrompt | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(
            r: ApproveOptionsResult | ApproveOptionsEditPrompt | None,
        ) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal(choice="epic", capacity=3)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsResult)
        assert result.choice == "tale"
        assert result.capacity is None
        assert modal._capacity == 3


async def test_c_key_is_disabled_for_tale_actions() -> None:
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal(choice="tale", capacity=3)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()

        assert not isinstance(pilot.app.screen, _CapacityInputModal)
        assert modal._capacity == 3
        display = modal.query_one("#approval-capacity-display", Static)
        assert "n/a (epic only)" in str(display.render())

        await pilot.press("e")
        await pilot.pause()
        assert "3" in str(display.render())
        assert not display.has_class("disabled")


async def test_p_key_preserves_capacity_in_edit_prompt() -> None:
    result: ApproveOptionsResult | ApproveOptionsEditPrompt | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(
            r: ApproveOptionsResult | ApproveOptionsEditPrompt | None,
        ) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal(
            choice="epic",
            coder_prompt="existing prompt",
            wait_spec="sase-a.1",
            capacity=0,
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("p")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsEditPrompt)
        assert result.choice == "epic"
        assert result.capacity == 0
        assert result.wait_spec == "sase-a.1"
