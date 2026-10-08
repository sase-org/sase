"""Focus, draft, result, and key-action behavior for the plan modal.

This mixin owns everything
:class:`~sase.ace.tui.modals.plan_approval_modal.PlanApprovalModal` does:
mount wiring, control focus movement, decision-draft edits, building
:mod:`~sase.ace.tui.modals.plan_approval_results` results from the selected
options, and the copy/debug/scroll key actions. Rendering lives in
:mod:`~sase.ace.tui.modals.plan_approval_modal_view`.
"""

from __future__ import annotations

import os
from typing import Any

from sase.notification_gates.debug import GateDebugContext

from ..actions.clipboard import schedule_copy_delivery
from ._plan_approval_modal_state import DECISIONS_FROZEN_MESSAGE, esc_drafts
from .gate_branch_controls import GateBranchControls, GateBranchData
from .plan_approval_decisions import build_decision_option_inputs
from .plan_approval_results import (
    PendingApproveState,
    PlanApprovalChoice,
    PlanApprovalResult,
)
from .plan_decision_document import cache_callout_spans
from .plan_decision_rows import PlanDecisionRows
from .plan_decision_sheet import PlanDecisionDraft

__all__ = ["PlanApprovalControlsMixin"]


class PlanApprovalControlsMixin:
    """Wire reviewer input to modal results."""

    _gate: GateBranchData
    _default_choice: PlanApprovalChoice
    _plan_file: str
    _copy_plan_path: str
    _plan_content: str | None
    _pending_approve_state: PendingApproveState | None
    _debug_context: GateDebugContext | None
    _decision_definitions: list[dict[str, Any]]
    _decision_draft: PlanDecisionDraft
    _review_revision: int | None
    _request_id: str | None
    _settled_text: str | None
    _callout_spans: list[dict[str, Any]]

    def _gate_control_ids(self) -> list[str]:
        try:
            controls = self._mounted_action_controls()  # type: ignore[attr-defined]
            action_ids = [] if controls is None else controls.control_ids()
        except Exception:
            action_ids = []
        decision_ids: list[str] = []
        try:
            rows = self.query_one("#plan-decision-rows", PlanDecisionRows)  # type: ignore[attr-defined]
            decision_ids = rows.visible_control_ids()
        except Exception:
            if self.has_decisions:  # type: ignore[attr-defined]
                decision_ids = [
                    f"plan-decision-{index}"
                    for index in range(len(self._decision_definitions))
                ]
        try:
            branch = self.query_one(GateBranchControls)  # type: ignore[attr-defined]
            branch_ids = branch.visible_control_ids()
        except Exception:
            branch_ids = []
        return [*action_ids, *decision_ids, *branch_ids]

    def focus_gate_control(self, delta: int) -> None:  # type: ignore[override]
        control_ids = self._gate_control_ids()
        if not control_ids:
            return
        try:
            from textual.widget import Widget

            focused = self.screen.focused  # type: ignore[attr-defined]
            focused_id = focused.id if isinstance(focused, Widget) else None
            try:
                current = control_ids.index(focused_id or "")
            except ValueError:
                current = -1 if delta > 0 else 0
            target = control_ids[(current + delta) % len(control_ids)]
            self.query_one(f"#{target}").focus(scroll_visible=False)  # type: ignore[attr-defined]
            self._sync_focused_decision(target)
        except Exception:
            pass

    def _sync_focused_decision(self, target_id: str) -> None:
        if not target_id.startswith("plan-decision-"):
            return
        try:
            index = int(target_id.rsplit("-", 1)[1])
        except ValueError:
            return
        try:
            rows = self.query_one("#plan-decision-rows", PlanDecisionRows)  # type: ignore[attr-defined]
            rows.set_focused_index(index)
        except Exception:
            pass
        self._scroll_to_focused_decision()  # type: ignore[attr-defined]

    def _focused_decision_id(self) -> str | None:
        try:
            rows = self.query_one("#plan-decision-rows", PlanDecisionRows)  # type: ignore[attr-defined]
            return rows.focused_id
        except Exception:
            return None

    def _apply_draft_edit(self, func: Any) -> None:
        if self._settled_text is not None:
            try:
                self.notify("Settled elsewhere; submit is disabled", severity="warning")  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        if not self.has_decisions:  # type: ignore[attr-defined]
            return
        func()
        if self._request_id is not None:
            esc_drafts[self._request_id] = self._decision_draft.values()
        self._refresh_verdict_summary()  # type: ignore[attr-defined]
        self._scroll_to_focused_decision()  # type: ignore[attr-defined]

    def on_mount(self) -> None:
        self._sync_submission_block()  # type: ignore[attr-defined]
        # Cache callout spans once; never validate on keypress.
        content = (
            self._plan_content
            if self._plan_content is not None
            else self._read_plan_file()  # type: ignore[attr-defined]
        )
        tier = "epic" if self._default_choice == "epic" else "tale"
        if getattr(self, "_last_fold_content", None) != content:
            try:
                self._callout_spans = cache_callout_spans(content, tier)
            except Exception:
                self._callout_spans = []
            try:
                self._ensure_fold_cache(content)  # type: ignore[attr-defined]
            except Exception:
                pass
        # First display: tint the folded document from the cached spans.
        try:
            from textual.widgets import Static as _Static

            folded = getattr(self, "_folded_text", None) or content
            self.query_one("#plan-approval-content", _Static).update(  # type: ignore[attr-defined]
                self._document_renderable(folded)  # type: ignore[attr-defined]
            )
        except Exception:
            pass
        if self._settled_text is not None:
            try:
                branch = self.query_one(GateBranchControls)  # type: ignore[attr-defined]
                branch.block_submission("Settled elsewhere; submit is disabled")
            except Exception:
                pass
            return
        if self._pending_approve_state is not None:
            state = self._pending_approve_state
            self._pending_approve_state = None
            self._push_approve_options(  # type: ignore[attr-defined]
                commit_plan=state.commit_plan,
                run_coder=state.run_coder,
                coder_prompt=state.coder_prompt,
                coder_model=state.coder_model,
                wait_spec=state.wait_spec,
                capacity=state.capacity,
                choice=state.choice,
            )
            return
        if self.has_decisions:  # type: ignore[attr-defined]
            try:
                self.query_one("#plan-decision-0").focus(scroll_visible=False)  # type: ignore[attr-defined]
                try:
                    rows = self.query_one("#plan-decision-rows", PlanDecisionRows)  # type: ignore[attr-defined]
                    rows.set_focused_index(0)
                except Exception:
                    pass
                self._scroll_to_focused_decision()  # type: ignore[attr-defined]
                return
            except Exception:
                pass
        self.focus_gate_control(1)

    def _decision_inputs_for(
        self, selected_option_ids: tuple[str, ...]
    ) -> dict[str, dict[str, Any]]:
        if not self.has_decisions:  # type: ignore[attr-defined]
            return {}
        if selected_option_ids == ("reject",):
            return {}
        return build_decision_option_inputs(
            self._gate, selected_option_ids, self._decision_draft.decision_map()
        )

    def _result_for_selection(  # type: ignore[override]
        self,
        selected_option_ids: tuple[str, ...],
        *,
        feedback: str | None = None,
        coder_prompt: str | None = None,
        coder_model: str | None = None,
        wait_spec: str | None = None,
        capacity: int | None = None,
        option_inputs: Any | None = None,
    ) -> PlanApprovalResult:
        from .plan_approval_results import plan_approval_result_for_selection

        result = plan_approval_result_for_selection(
            selected_option_ids,
            epic=self._default_choice == "epic",
            feedback=feedback,
            coder_prompt=coder_prompt,
            coder_model=coder_model,
            wait_spec=wait_spec,
            capacity=capacity,
            option_inputs=option_inputs,
        )
        return self._result_with_decisions(result)

    def action_approve(self) -> None:  # type: ignore[override]
        from .plan_approval_results import plan_approval_result_for_choice

        if not self._choice_allowed("approve"):  # type: ignore[attr-defined]
            return
        self.dismiss(  # type: ignore[attr-defined]
            self._result_with_decisions(plan_approval_result_for_choice("approve"))
        )

    def action_tale(self) -> None:  # type: ignore[override]
        from .plan_approval_results import plan_approval_result_for_choice

        if not self._choice_allowed("tale"):  # type: ignore[attr-defined]
            return
        self.dismiss(  # type: ignore[attr-defined]
            self._result_with_decisions(plan_approval_result_for_choice("tale"))
        )

    def action_epic(self) -> None:  # type: ignore[override]
        from .plan_approval_results import plan_approval_result_for_choice

        if not self._choice_allowed("epic"):  # type: ignore[attr-defined]
            return
        self.dismiss(  # type: ignore[attr-defined]
            self._result_with_decisions(plan_approval_result_for_choice("epic"))
        )

    def action_reject(self) -> None:  # type: ignore[override]
        result = PlanApprovalResult(action="reject")
        result.review_revision = self._review_revision
        self.dismiss(result)  # type: ignore[attr-defined]

    def action_feedback(self) -> None:  # type: ignore[override]
        # Attach hidden sheet values via feedback_requested; the host
        # threads carries + decision values through PlanFeedbackContext.
        result = PlanApprovalResult(action="feedback_requested")
        result.review_revision = self._review_revision
        if self.has_decisions:  # type: ignore[attr-defined]
            decision_inputs = build_decision_option_inputs(
                self._gate, ("feedback",), self._decision_draft.decision_map()
            )
            if decision_inputs.get("feedback"):
                result.option_inputs = decision_inputs
        self.dismiss(result)  # type: ignore[attr-defined]

    def _result_with_decisions(self, result: PlanApprovalResult) -> PlanApprovalResult:
        if not self.has_decisions:  # type: ignore[attr-defined]
            result.review_revision = self._review_revision
            return result
        if result.selected_option_ids == ("reject",):
            result.review_revision = self._review_revision
            return result
        decision_inputs = self._decision_inputs_for(result.selected_option_ids)
        if decision_inputs:
            merged: dict[str, dict[str, Any]] = {
                key: dict(value)
                for key, value in dict(result.option_inputs or {}).items()
            }
            for option_id, values in decision_inputs.items():
                existing = dict(merged.get(option_id, {}))
                existing.update(values)
                merged[option_id] = existing
            result.option_inputs = merged
        result.review_revision = self._review_revision
        return result

    def on_gate_branch_controls_resolved(
        self, event: GateBranchControls.Resolved
    ) -> None:
        if self._settled_text is not None:
            event.stop()
            try:
                self.notify("Settled elsewhere; submit is disabled", severity="warning")  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        event.stop()
        result = self._result_for_selection(
            event.selected_option_ids,
            feedback=event.feedback,
            option_inputs=event.option_inputs,
        )
        self.dismiss(self._result_with_decisions(result))  # type: ignore[attr-defined]

    def action_cancel(self) -> None:
        """Cancel the modal (no response written)."""
        if self._request_id is not None and self.has_decisions:  # type: ignore[attr-defined]
            esc_drafts[self._request_id] = self._decision_draft.values()
        self.dismiss(None)  # type: ignore[attr-defined]

    def action_debug_view(self) -> None:
        from .gate_debug_modal import show_gate_debug

        show_gate_debug(self, self._debug_context)

    def action_next_control(self) -> None:
        self.focus_gate_control(1)

    def action_previous_control(self) -> None:
        self.focus_gate_control(-1)

    def action_toggle_option(self) -> None:
        focused_id = None
        try:
            from textual.widget import Widget

            focused = self.screen.focused  # type: ignore[attr-defined]
            focused_id = focused.id if isinstance(focused, Widget) else None
        except Exception:
            focused_id = None
        if focused_id is not None and focused_id.startswith("plan-decision-"):
            decision_id = self._focused_decision_id()
            if decision_id is not None:
                self._apply_draft_edit(lambda: self._decision_draft.flip(decision_id))
            return
        self.query_one(GateBranchControls).toggle_focused_option()  # type: ignore[attr-defined]

    def action_decision_next(self) -> None:
        decision_id = self._focused_decision_id()
        if decision_id is None:
            return
        self._apply_draft_edit(lambda: self._decision_draft.step(decision_id, 1))

    def action_decision_prev(self) -> None:
        decision_id = self._focused_decision_id()
        if decision_id is None:
            return
        self._apply_draft_edit(lambda: self._decision_draft.step(decision_id, -1))

    def action_decision_reset(self) -> None:
        decision_id = self._focused_decision_id()
        if decision_id is None:
            return
        self._apply_draft_edit(lambda: self._decision_draft.reset(decision_id))

    def action_decision_reset_all(self) -> None:
        self._apply_draft_edit(self._decision_draft.reset_all)

    def action_submit_primary(self) -> None:
        self.query_one(GateBranchControls).submit_primary_branch()  # type: ignore[attr-defined]

    def action_submit_branch(self) -> None:
        self.query_one(GateBranchControls).submit_active_branch()  # type: ignore[attr-defined]

    def action_submit_numbered_branch(self, branch_index: int) -> None:
        self.query_one(GateBranchControls).submit_numbered_branch(branch_index)  # type: ignore[attr-defined]

    def action_open_inputs(self) -> None:
        self.query_one(GateBranchControls).open_inputs_for_focused_control()  # type: ignore[attr-defined]

    def action_copy_plan(self) -> None:
        """Copy the plan file contents to clipboard."""

        def content() -> str:
            value = (
                self._plan_content
                if self._plan_content is not None
                else self._read_plan_file()  # type: ignore[attr-defined]
            )
            if value.startswith("[Error"):
                raise RuntimeError("failed to read plan file")
            return value

        schedule_copy_delivery(
            self,
            content,
            copied_label="all plan contents",
            task_name="sase-copy-plan-contents",
        )

    def _copy_plan_path_to_clipboard(self) -> None:
        """Copy the plan file path to clipboard (with ~ for home dir)."""
        home = os.path.expanduser("~")
        path = os.path.expanduser(self._copy_plan_path)
        if path.startswith(home):
            path = "~" + path[len(home) :]
        schedule_copy_delivery(
            self,
            path,
            copied_label=f"plan path ({path})",
            task_name="sase-copy-plan-path",
        )

    def action_copy_plan_path(self) -> None:
        """Copy the plan file path to clipboard (with ~ for home dir)."""
        self._copy_plan_path_to_clipboard()

    def _apply_edit_outcome(self, operation_id: str, outcome: Any) -> None:
        message = str(getattr(outcome, "message", "") or "")
        frozen_head, _, _ = DECISIONS_FROZEN_MESSAGE.partition(". ")
        if frozen_head in message:
            # Freeze still leaves an unaccepted draft: apply the base draft
            # banner + submission block, keeping the freeze sentence on top.
            try:
                content = getattr(outcome, "content", None)
                if content is not None:
                    self.render_reviewed_content(content)  # type: ignore[attr-defined]
                controls = self._mounted_action_controls()  # type: ignore[attr-defined]
                if controls is not None:
                    controls.set_draft(
                        operation_id if getattr(outcome, "draft", False) else None,
                        getattr(outcome, "draft_path", None),
                    )
                self._sync_submission_block()  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                self.notify(  # type: ignore[attr-defined]
                    message, title="Draft not accepted", severity="error", timeout=15
                )
            except Exception:
                pass
            return
        super()._apply_edit_outcome(operation_id, outcome)  # type: ignore[misc, attr-defined]
