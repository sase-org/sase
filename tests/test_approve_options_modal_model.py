"""Coder-model tests for the custom approval modal."""

from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.modals.approve_options_modal import (
    ApproveOptionsEditPrompt,
    ApproveOptionsModal,
    ApproveOptionsResult,
)
from tests.plan_validation_helpers import VALID_TALE_PLAN

from ._approve_options_modal_helpers import ApproveOptionsApp


def _write_tale_plan(tmp_path, *, size: str = "small") -> str:
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(
        VALID_TALE_PLAN.replace("size: small", f"size: {size}"),
        encoding="utf-8",
    )
    return str(plan_file)


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


async def test_default_model_shows_tale_size_alias_label(tmp_path) -> None:
    """No coder_model should display the resolved tale-size alias."""
    plan_file = _write_tale_plan(tmp_path, size="small")
    with patch(
        "sase.llm_provider.registry.resolve_model_provider",
        return_value=("claude", "opus"),
    ) as resolve_mock:
        async with ApproveOptionsApp().run_test() as pilot:
            modal = ApproveOptionsModal(plan_file=plan_file)
            pilot.app.push_screen(modal)
            await pilot.pause()

            model_display = modal.query_one("#coder-model-display", Static)
            display_text = str(model_display.render())
            assert "Follow-up — CLAUDE(opus)" in display_text
    resolve_mock.assert_any_call("@small_phase_worker")


async def test_default_model_uses_validated_tale_size(tmp_path) -> None:
    """The default resolves the approved tale's phase-worker size alias."""
    plan_file = _write_tale_plan(tmp_path, size="medium")
    with patch(
        "sase.llm_provider.registry.resolve_model_provider",
        return_value=("codex", "gpt-5.6-sol"),
    ) as resolve_mock:
        async with ApproveOptionsApp().run_test() as pilot:
            modal = ApproveOptionsModal(
                planner_llm_provider="claude",
                plan_file=plan_file,
            )
            pilot.app.push_screen(modal)
            await pilot.pause()

            model_display = modal.query_one("#coder-model-display", Static)
            display_text = str(model_display.render())
            assert "Follow-up — CODEX(gpt-5.6-sol)" in display_text
    resolve_mock.assert_any_call("@medium_phase_worker")


async def test_default_model_without_plan_file_uses_medium_fallback() -> None:
    """The modal has a medium fallback before a plan path is available."""
    with patch(
        "sase.llm_provider.registry.resolve_model_provider",
        return_value=("claude", "opus"),
    ) as resolve_mock:
        async with ApproveOptionsApp().run_test() as pilot:
            modal = ApproveOptionsModal()
            pilot.app.push_screen(modal)
            await pilot.pause()

            model_display = modal.query_one("#coder-model-display", Static)
            assert "Follow-up — CLAUDE(opus)" in str(model_display.render())
    resolve_mock.assert_any_call("@medium_phase_worker")


async def test_epic_model_is_configured_by_plan_frontmatter() -> None:
    """Epic approval does not expose the retired creator-model lane."""
    with patch(
        "sase.llm_provider.registry.resolve_model_provider",
        return_value=("claude", "opus"),
    ) as resolve_mock:
        async with ApproveOptionsApp().run_test() as pilot:
            modal = ApproveOptionsModal(choice="epic")
            pilot.app.push_screen(modal)
            await pilot.pause()

            model_display = modal.query_one("#coder-model-display", Static)
            display_text = str(model_display.render())
            assert "Configured by epic plan frontmatter" in display_text
    resolve_mock.assert_not_called()


async def test_model_picker_resets_coder_model_to_followup_default() -> None:
    """Re-opening the picker and choosing the default resets a selected model."""
    with patch(
        "sase.llm_provider.registry.resolve_model_provider",
        return_value=("claude", "opus"),
    ):
        async with ApproveOptionsApp().run_test() as pilot:
            modal = ApproveOptionsModal(coder_model="sonnet")
            pilot.app.push_screen(modal)
            await pilot.pause()

            # Open the picker and select the highlighted "Follow-up default".
            await pilot.press("m")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            assert modal._coder_model is None
            model_display = modal.query_one("#coder-model-display", Static)
            assert "Follow-up — CLAUDE(opus)" in str(model_display.render())


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
