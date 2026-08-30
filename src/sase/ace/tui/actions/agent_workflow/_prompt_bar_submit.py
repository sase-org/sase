"""Submit/cancel event handlers for the agent prompt input bar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..agents._notification_utils import (
    refresh_notification_agent_or_request,
    request_notification_agents_refresh,
)
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
            # A multi-pane single submit with an empty pane is dropped by the
            # widget without posting, so an empty value here is always a
            # whole-bar submit: cancel and unmount as before.
            self.notify("Empty prompt - cancelled", severity="warning")  # type: ignore[attr-defined]
            self._unmount_prompt_bar()  # type: ignore[attr-defined]
            self._prompt_context = None
            return

        # ``keep_bar`` is set for a single-pane submit while other panes remain:
        # launch the selected pane but leave the bar mounted (and the base
        # prompt context intact) so the remaining panes can be submitted next.
        self._finish_agent_launch(prompt, keep_bar=event.keep_bar)  # type: ignore[attr-defined]

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

        if event.keep_bar:
            # Per-pane cancel in a multi-pane stack: the widget already removed
            # the pane and kept the bar mounted, so just record that pane's text
            # as cancelled history. The base prompt context stays valid for the
            # remaining panes.
            stored = self._save_text_as_cancelled(event.cancelled_text)  # type: ignore[attr-defined]
            if stored:
                self._notify_prompt_cancelled(stored, pane=True)
            return

        if not event.record_segments:
            # All-pane cancel: the widget emitted the canonical joined stack.
            # Save that exact prompt once, then detach without the ordinary
            # unmount safety net re-reading and writing it a second time.
            stored = self._save_text_as_cancelled(  # type: ignore[attr-defined]
                event.cancelled_text,
                record_segments=False,
            )
            self._unmount_prompt_bar_without_cancel_save()  # type: ignore[attr-defined]
            self._prompt_context = None
            if stored:
                self._notify_prompt_cancelled(stored, pane=False)
            return

        stored = self._unmount_prompt_bar()  # type: ignore[attr-defined]
        self._prompt_context = None
        if stored:
            self._notify_prompt_cancelled(stored, pane=False)

    def _notify_prompt_cancelled(self, stored_text: str, *, pane: bool) -> None:
        """Show the prompt-history receipt toast for a cancelled prompt."""
        from sase.history.prompt_stats import short_preview

        title = "Prompt pane cancelled" if pane else "Prompt input cancelled"
        self.notify(  # type: ignore[attr-defined]
            f'"{short_preview(stored_text)}"',
            title=f"{title} — saved to history",
        )

    def _handle_plan_feedback_submitted(self, feedback: str) -> None:
        """Handle submission of plan feedback via the PromptInputBar."""
        import json

        from sase.notifications import mark_dismissed

        ctx = self._plan_feedback_context
        if ctx is None:
            self.notify("No plan feedback context", severity="warning")  # type: ignore[attr-defined]
            return

        if ctx.notification is not None:
            from sase.notification_gates.paths import resolve_notification_bundle

            bundle = resolve_notification_bundle(ctx.notification)
            if bundle is not None and not bundle.legacy:
                from sase.ace.tui.actions.agents._notification_modals import (
                    submit_neutral_plan_response,
                )
                from sase.ace.tui.actions.agents._notification_navigation import (
                    find_agent_for_notification,
                )
                from sase.ace.tui.modals.plan_approval_modal import PlanApprovalResult

                agent = find_agent_for_notification(self, ctx.notification)
                submitted = submit_neutral_plan_response(
                    self,
                    ctx.notification,
                    agent,
                    PlanApprovalResult(action="reject", feedback=feedback),
                )
                if submitted:
                    self._plan_feedback_context = None
                    self._unmount_prompt_bar()  # type: ignore[attr-defined]
                return

        # Write a legacy plan_response.json with reject + feedback
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
            agent = next(
                (
                    candidate
                    for candidate in getattr(self, "_agents", [])
                    if candidate.identity == ctx.agent_identity
                ),
                None,
            )
            if agent is not None:
                refresh_notification_agent_or_request(self, agent=agent)
            else:
                request_notification_agents_refresh(self)

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
                wait_spec=ctx.wait_spec,
                choice=ctx.choice,
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
                wait_spec=ctx.wait_spec,
                choice=ctx.choice,
            ),
        )
