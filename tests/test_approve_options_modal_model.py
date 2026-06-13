"""Coder-model tests for the custom approval modal."""

from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.modals.approve_options_modal import (
    ApproveOptionsEditPrompt,
    ApproveOptionsModal,
    ApproveOptionsResult,
)

from ._approve_options_modal_helpers import ApproveOptionsApp


async def test_m_key_opens_model_picker() -> None:
    """Pressing 'm' should keep model selection reachable for every action."""
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal(choice="approve")
        pilot.app.push_screen(modal)
        await pilot.pause()

        screen_count_before = len(pilot.app.screen_stack)
        await pilot.press("m")
        await pilot.pause()

        assert len(pilot.app.screen_stack) == screen_count_before + 1


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
        assert result.choice == "tale"
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
        assert result.choice == "tale"
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


async def test_default_model_shows_worker_label() -> None:
    """No coder_model should display the resolved worker-lane model."""
    with patch(
        "sase.llm_provider.resolve_effective_worker_provider_model",
        return_value=("claude", "opus"),
    ):
        async with ApproveOptionsApp().run_test() as pilot:
            modal = ApproveOptionsModal()
            pilot.app.push_screen(modal)
            await pilot.pause()

            model_display = modal.query_one("#coder-model-display", Static)
            display_text = str(model_display.render())
            assert "Worker — CLAUDE(opus)" in display_text


async def test_default_model_uses_planner_contextual_worker_lane() -> None:
    """With planner context, the default shows that planner's worker lane."""
    from sase.llm_provider import WorkerModelResolution

    resolution = WorkerModelResolution(
        provider="codex",
        model="gpt-5.5",
        source="config",
        primary_provider="claude",
        primary_model="opus",
        matched_key="claude/opus",
        configured_target="codex/gpt-5.5",
    )
    with patch(
        "sase.llm_provider.resolve_worker_provider_model_for_primary",
        return_value=resolution,
    ) as resolve_mock:
        async with ApproveOptionsApp().run_test() as pilot:
            modal = ApproveOptionsModal(
                planner_llm_provider="claude",
                planner_model="opus",
            )
            pilot.app.push_screen(modal)
            await pilot.pause()

            model_display = modal.query_one("#coder-model-display", Static)
            display_text = str(model_display.render())
            assert "Worker — CODEX(gpt-5.5)" in display_text
    resolve_mock.assert_called_once_with("claude", "opus")


async def test_model_picker_resets_coder_model_to_worker_default() -> None:
    """Re-opening the picker and choosing the default resets a selected model."""
    with patch(
        "sase.llm_provider.resolve_effective_worker_provider_model",
        return_value=("claude", "opus"),
    ):
        async with ApproveOptionsApp().run_test() as pilot:
            modal = ApproveOptionsModal(coder_model="sonnet")
            pilot.app.push_screen(modal)
            await pilot.pause()

            # Open the picker and select the highlighted "Worker model (default)".
            await pilot.press("m")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            assert modal._coder_model is None
            model_display = modal.query_one("#coder-model-display", Static)
            assert "Worker — CLAUDE(opus)" in str(model_display.render())


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
