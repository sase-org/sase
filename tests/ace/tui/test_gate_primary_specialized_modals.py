"""Enter-to-primary coverage for specialized notification gate modals."""

from textual.app import App

from sase.ace.tui.modals.launch_approval_modal import (
    LaunchApprovalModal,
    LaunchApprovalResult,
)
from sase.ace.tui.modals.user_question_modal import (
    UserQuestionModal,
    UserQuestionResult,
)
from sase.ace.tui.modals.workflow_hitl_modal import (
    WorkflowHITLInput,
    WorkflowHITLModal,
)
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.xprompt.workflow_executor_types import HITLResult


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False


async def test_enter_approves_launch_gate() -> None:
    results: list[LaunchApprovalResult | None] = []
    modal = LaunchApprovalModal(preview_file=None, request_id="launch-primary")

    async with _TestApp().run_test(size=(100, 30)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert results == [LaunchApprovalResult(action="approve")]


async def test_enter_accepts_workflow_hitl_gate() -> None:
    results: list[HITLResult | None] = []
    modal = WorkflowHITLModal(
        WorkflowHITLInput(
            step_name="review",
            step_type="agent",
            output={"status": "ready"},
            workflow_name="test",
        )
    )

    async with _TestApp().run_test(size=(100, 30)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert len(results) == 1
    assert results[0] is not None
    assert results[0].action == "accept"
    assert results[0].approved is True


async def test_question_space_toggles_and_enter_submits_answers() -> None:
    results: list[UserQuestionResult | None] = []
    modal = UserQuestionModal(
        [
            {
                "question": "Choose one",
                "options": [{"label": "First", "description": "Primary choice"}],
            }
        ]
    )

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("space")
        await pilot.press("enter")
        await pilot.pause()

    assert results[0] is not None
    assert results[0].answers[0].selected == ["First"]


async def test_question_free_text_enter_finishes_input_before_submit() -> None:
    results: list[UserQuestionResult | None] = []
    modal = UserQuestionModal([{"question": "Anything else?", "options": []}])

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("space")
        other = modal.query_one("#user-question-other-input", SingleLineVimTextArea)
        other.text = "Keep the rollout reversible"
        await pilot.press("enter")
        await pilot.pause()
        assert results == []
        await pilot.press("enter")
        await pilot.pause()

    assert results[0] is not None
    assert results[0].answers[0].selected == ["Other"]
    assert results[0].answers[0].custom_feedback == "Keep the rollout reversible"
