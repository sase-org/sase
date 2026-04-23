"""Submit/cancel event handlers for the agent prompt input bar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._types import PromptContext

if TYPE_CHECKING:
    from sase.ace.tui.actions.agents._types import (
        ApprovePromptContext,
        PlanFeedbackContext,
    )


class PromptBarSubmitMixin:
    """Prompt input bar submit/cancel + plan-feedback + approve-prompt handlers."""

    _prompt_context: PromptContext | None
    _plan_feedback_context: PlanFeedbackContext | None
    _approve_prompt_context: ApprovePromptContext | None

    def on_prompt_input_bar_submitted(self, event: object) -> None:
        """Handle prompt submission from the input bar."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.Submitted):
            return

        if event.mode == "feedback":
            self._handle_plan_feedback_submitted(event.value)
            return

        if event.mode == "approve_prompt":
            self._handle_approve_prompt_submitted(event.value)
            return

        prompt = event.value
        if not prompt:
            self.notify("Empty prompt - cancelled", severity="warning")  # type: ignore[attr-defined]
            self._unmount_prompt_bar()  # type: ignore[attr-defined]
            self._prompt_context = None
            return

        self._finish_agent_launch(prompt)  # type: ignore[attr-defined]

    def on_prompt_input_bar_cancelled(self, event: object) -> None:
        """Handle cancellation from the input bar."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.Cancelled):
            return

        if event.mode == "feedback":
            self._handle_plan_feedback_cancelled()
            return

        if event.mode == "approve_prompt":
            self._handle_approve_prompt_cancelled()
            return

        self.notify("Prompt input cancelled")  # type: ignore[attr-defined]
        self._unmount_prompt_bar()  # type: ignore[attr-defined]  # saves text automatically
        self._prompt_context = None

    def _handle_plan_feedback_submitted(self, feedback: str) -> None:
        """Handle submission of plan feedback via the PromptInputBar."""
        import json

        from sase.notifications import mark_dismissed

        ctx = self._plan_feedback_context
        if ctx is None:
            self.notify("No plan feedback context", severity="warning")  # type: ignore[attr-defined]
            return

        # Write plan_response.json with reject + feedback
        plan_response_path = ctx.response_path / "plan_response.json"
        response_data: dict[str, object] = {
            "action": "reject",
            "feedback": feedback,
        }
        try:
            with open(plan_response_path, "w", encoding="utf-8") as f:
                json.dump(response_data, f, indent=2)
            self.notify("Sent plan feedback")  # type: ignore[attr-defined]
        except Exception as e:
            self.notify(f"Error writing response: {e}", severity="error")  # type: ignore[attr-defined]
            return

        # Dismiss notification
        mark_dismissed(ctx.notification_id)

        # Update agent status override to RUNNING
        if ctx.agent_identity is not None:
            self._agent_status_overrides[ctx.agent_identity] = "RUNNING"  # type: ignore[attr-defined]
            self._load_agents()  # type: ignore[attr-defined]

        # Clean up
        self._plan_feedback_context = None
        self._unmount_prompt_bar()  # type: ignore[attr-defined]
        self._refresh_notification_count()  # type: ignore[attr-defined]

    def _handle_plan_feedback_cancelled(self) -> None:
        """Handle cancellation of plan feedback."""
        self._plan_feedback_context = None
        self._unmount_prompt_bar()  # type: ignore[attr-defined]
        self.notify("Plan feedback cancelled")  # type: ignore[attr-defined]

    def _handle_approve_prompt_submitted(self, prompt: str) -> None:
        """Handle submission of coder prompt editing via the PromptInputBar."""
        from ...modals.plan_approval_modal import PendingApproveState

        ctx = self._approve_prompt_context
        if ctx is None:
            self.notify("No approve prompt context", severity="warning")  # type: ignore[attr-defined]
            return

        self._approve_prompt_context = None
        self._unmount_prompt_bar()  # type: ignore[attr-defined]

        from sase.ace.tui.actions.agents._notification_modals import (
            handle_plan_approval,
        )

        handle_plan_approval(
            self,
            ctx.notification,
            pending_approve_state=PendingApproveState(
                commit_plan=ctx.commit_plan,
                run_coder=ctx.run_coder,
                coder_prompt=prompt,
                coder_model=ctx.coder_model,
            ),
        )

    def _handle_approve_prompt_cancelled(self) -> None:
        """Handle cancellation of coder prompt editing -- preserve original prompt."""
        from ...modals.plan_approval_modal import PendingApproveState

        ctx = self._approve_prompt_context
        if ctx is None:
            self._unmount_prompt_bar()  # type: ignore[attr-defined]
            return

        self._approve_prompt_context = None
        self._unmount_prompt_bar()  # type: ignore[attr-defined]

        from sase.ace.tui.actions.agents._notification_modals import (
            handle_plan_approval,
        )

        handle_plan_approval(
            self,
            ctx.notification,
            pending_approve_state=PendingApproveState(
                commit_plan=ctx.commit_plan,
                run_coder=ctx.run_coder,
                coder_prompt=ctx.current_prompt,
                coder_model=ctx.coder_model,
            ),
        )
