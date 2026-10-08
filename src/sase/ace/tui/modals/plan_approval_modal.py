"""Plan approval modal for sase's TUI.

This module owns the modal itself: its layout, its scrolling and copy
shortcuts, and how it is wired to the shared gate machinery. The pieces that
are not about the screen live beside it — the branch model defaults in
:mod:`~sase.ace.tui.modals.plan_approval_gate_data`, the result protocol in
:mod:`~sase.ace.tui.modals.plan_approval_results`, the decision handling in
:mod:`~sase.ace.tui.modals.plan_approval_decisions`, and the hint line in
:mod:`~sase.ace.tui.modals.plan_approval_footer`.
"""

import os
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.notification_gates.debug import GateDebugContext

from ..actions.clipboard import schedule_copy_delivery
from ..keymaps import (
    GateModalKeymaps,
    build_gate_modal_bindings,
    build_gate_numbered_branch_bindings,
)
from ..util.frontmatter_syntax import markdown_document_syntax
from .base import CopyModeForwardingMixin
from .gate_action_controls import GateActionsData
from .gate_action_runner import (
    GateActionRunner,
    GateActionsMixin,
    gate_modal_taken_keys,
)
from .gate_branch_controls import GateBranchControls, GateBranchData
from .plan_approval_decisions import (
    PlanApprovalDecisionsMixin,
    build_decision_option_inputs,
)
from .plan_approval_footer import plan_approval_footer_text
from .plan_approval_gate_data import (
    DEFAULT_GATE_KEYMAPS,
    HOST_COLLECTED_PROPERTIES,
    PLAN_GATE_STATIC_BINDINGS,
    default_plan_gate_data,
)
from .plan_approval_results import (
    PendingApproveState,
    PlanApprovalChoice,
    PlanApprovalResult,
)
from .plan_decision_document import (
    cache_callout_spans,
    fold_plan_decisions_content,
    scroll_target_for_decision,
)
from .plan_decision_rows import PlanDecisionRows
from .plan_decision_sheet import PlanDecisionDraft, verdict_for_selection


def _provider_badge_markup(llm_provider: str | None, model: str | None) -> str:
    """Render a Rich-markup badge like ``CLAUDE(opus)`` with provider theming.

    Returns an empty string when neither field is set, so callers can collapse
    the title to its unbadged form.
    """
    from sase.ace.tui.provider_styles import provider_model_badge_markup

    return provider_model_badge_markup(llm_provider, model)


_DECISIONS_FROZEN_MESSAGE = (
    "Decisions are fixed for this review. Change answers in the Decisions panel, "
    "or send feedback to change the questions."
)

# Esc draft store: request id -> draft values, for the life of the process.
_ESC_DRAFTS: dict[str, dict[str, Any]] = {}


def _short_verdict_label(epic: bool, commit_plan: bool, run_coder: bool) -> str:
    if epic:
        return "Epic"
    if commit_plan and run_coder:
        return "Tale"
    if run_coder:
        return "Coder"
    return "Commit"


class PlanApprovalModal(
    PlanApprovalDecisionsMixin,
    GateActionsMixin,
    CopyModeForwardingMixin,
    ModalScreen[PlanApprovalResult | None],
):
    """Modal for reviewing and approving/rejecting a Claude Code plan."""

    HORIZONTAL_BREAKPOINTS = [
        (0, "-gate-review-narrow"),
        (100, "-gate-review-wide"),
    ]

    BINDINGS = [
        *PLAN_GATE_STATIC_BINDINGS,
        *build_gate_modal_bindings(DEFAULT_GATE_KEYMAPS),
        *build_gate_numbered_branch_bindings(),
    ]

    def __init__(
        self,
        plan_file: str,
        pending_approve_state: PendingApproveState | None = None,
        *,
        copy_plan_path: str | None = None,
        llm_provider: str | None = None,
        model: str | None = None,
        default_choice: PlanApprovalChoice | None = None,
        gate: GateBranchData | None = None,
        plan_content: str | None = None,
        debug_context: GateDebugContext | None = None,
        gate_keymaps: GateModalKeymaps | None = None,
        actions: GateActionsData | None = None,
        action_runner: GateActionRunner | None = None,
        decision_definitions: list[dict[str, Any]] | None = None,
        review_revision: int | None = None,
        request_id: str | None = None,
        settled_text: str | None = None,
    ) -> None:
        """Initialize the plan approval modal.

        Args:
            plan_file: Path to the plan markdown file.
            pending_approve_state: If set, auto-push the custom approval modal on mount
                with the given state (used after prompt editing round-trip).
            copy_plan_path: Durable plan path copied by the path shortcut. Falls back
                to ``plan_file`` for direct and legacy callers.
            llm_provider: Provider that produced the plan (e.g. "claude"), for
                display in the modal title. Optional — when absent the title
                omits the provider badge.
            model: Model that produced the plan (e.g. "opus"), for display in
                the modal title alongside the provider.
            decision_definitions: Frozen ``payload.decisions`` vector. Direct
                callers that only pass a path keep an empty sheet.
            review_revision: Displayed gate envelope revision. ``None`` means
                unchecked (legacy notifications).
            request_id: Live-gate request id for Esc draft restore.
        """
        super().__init__()
        self._plan_file = plan_file
        self._copy_plan_path = copy_plan_path or plan_file
        self._pending_approve_state = pending_approve_state
        self._llm_provider = llm_provider
        self._model = model
        self._default_choice: PlanApprovalChoice = default_choice or "approve"
        self._gate = gate or default_plan_gate_data(self._default_choice)
        self._plan_content = plan_content
        self._debug_context = debug_context
        self._gate_keymaps = gate_keymaps or DEFAULT_GATE_KEYMAPS
        self._decision_definitions = list(decision_definitions or [])
        self._review_revision = review_revision
        self._request_id = request_id
        restored = None
        if request_id is not None and request_id in _ESC_DRAFTS:
            restored = _ESC_DRAFTS.get(request_id)
        self._decision_draft = PlanDecisionDraft(
            self._decision_definitions,
            values=restored,
            review_revision=int(review_revision or 0),
        )
        self._settled_text: str | None = settled_text
        self._fold_map: dict[int, int] = {}
        self._folded_line: int | None = None
        self._callout_spans: list[dict[str, Any]] = []
        self._init_gate_actions(
            actions,
            action_runner,
            taken_keys=gate_modal_taken_keys(
                PLAN_GATE_STATIC_BINDINGS, self._gate_keymaps
            ),
        )
        self._bindings = BindingsMap(
            [
                *PLAN_GATE_STATIC_BINDINGS,
                *build_gate_modal_bindings(self._gate_keymaps),
                *build_gate_numbered_branch_bindings(),
                *self._gate_action_bindings(),
            ]
        )

    @property
    def has_decisions(self) -> bool:
        return bool(self._decision_definitions)

    def _build_title_markup(self) -> str:
        """Return the Rich markup string used for the modal title."""
        badge = _provider_badge_markup(self._llm_provider, self._model)
        badge_segment = f"  {badge}" if badge else ""
        title = (
            "Epic Review"
            if getattr(self, "_default_choice", "approve") == "epic"
            else "Plan Review"
        )
        return f"[bold cyan]{title}[/bold cyan]{badge_segment}"

    def _decisions_header(self) -> str:
        total = len(self._decision_definitions)
        memos = sum(
            1 for d in self._decision_definitions if d.get("memory") is not None
        )
        return f"Decisions  {total} · 🧠 {memos}"

    def _current_verdict(self) -> str:
        epic = self._default_choice == "epic"
        try:
            controls = self.query_one(GateBranchControls)
            branch_index = next(
                index
                for index, branch in enumerate(self._gate.branches)
                if "approve" in branch
            )
            selected = set(controls.selected_option_ids(branch_index))
            from sase.plan_gate import PLAN_APPROVE_OPTION_ID, PLAN_COMMIT_OPTION_ID

            commit = PLAN_COMMIT_OPTION_ID in selected
            run = PLAN_APPROVE_OPTION_ID in selected
        except Exception:
            commit = True
            run = True
        return verdict_for_selection(commit_plan=commit, run_coder=run, epic=epic)

    def _enter_badge(self) -> Text:
        from .gate_primary_footer import primary_action_badge_for_label

        epic = self._default_choice == "epic"
        try:
            controls = self.query_one(GateBranchControls)
            branch_index = next(
                index
                for index, branch in enumerate(self._gate.branches)
                if "approve" in branch
            )
            selected = set(controls.selected_option_ids(branch_index))
            from sase.plan_gate import PLAN_APPROVE_OPTION_ID, PLAN_COMMIT_OPTION_ID

            commit = PLAN_COMMIT_OPTION_ID in selected
            run = PLAN_APPROVE_OPTION_ID in selected
        except Exception:
            commit = True
            run = True
        label = _short_verdict_label(epic, commit, run)
        if not self.has_decisions:
            return primary_action_badge_for_label(
                label, self._gate_keymaps.submit_primary
            )
        verdict = verdict_for_selection(commit_plan=commit, run_coder=run, epic=epic)
        short = self._decision_draft.short_summary(verdict)
        return primary_action_badge_for_label(
            f"{label} · {short}", self._gate_keymaps.submit_primary
        )

    def _verdict_summary_text(self) -> Text:
        if not self.has_decisions:
            return Text("")
        verdict = self._current_verdict()
        try:
            sentence = self._decision_draft.full_summary(verdict)
        except Exception:
            sentence = ""
        return Text(sentence, style="dim")

    def _display_content(self) -> str:
        content = (
            self._plan_content
            if self._plan_content is not None
            else self._read_plan_file()
        )
        folded, fold_map, _line, _count = fold_plan_decisions_content(content)
        self._fold_map = fold_map
        if fold_map:
            return folded
        return content

    def _refresh_verdict_summary(self) -> None:
        if not self.is_mounted:
            return
        try:
            summary = self.query_one("#plan-verdict-summary", Static)
            summary.update(self._verdict_summary_text())
        except Exception:
            pass
        try:
            footer = self.query_one("#plan-approval-footer", Static)
            footer.update(self._footer_text())
        except Exception:
            pass
        try:
            rows = self.query_one("#plan-decision-rows", PlanDecisionRows)
            rows.update_rows(self._decision_draft.sheet().get("rows", []))
        except Exception:
            pass

    def _scroll_to_focused_decision(self) -> None:
        if not self.has_decisions or not self.is_mounted:
            return
        try:
            rows = self.query_one("#plan-decision-rows", PlanDecisionRows)
            focused_id = rows.focused_id
        except Exception:
            return
        if not focused_id:
            return
        content = (
            self._plan_content
            if self._plan_content is not None
            else self._read_plan_file()
        )
        folded, fold_map, _line, _count = fold_plan_decisions_content(content)
        target = scroll_target_for_decision(
            focused_id, self._callout_spans, folded, fold_map or self._fold_map
        )
        if target is None:
            return
        try:
            scroll = self.query_one("#plan-approval-scroll", VerticalScroll)
            scroll.scroll_to(y=target, animate=False)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        rail_classes = "gate-review-actions"
        if self.has_decisions:
            rail_classes += " gate-review-actions--decisions"
        with Container(
            id="plan-approval-container",
            classes="gate-review-shell",
        ):
            yield Static(
                self._build_title_markup(),
                id="plan-approval-title",
                classes="gate-review-header",
            )

            with Container(classes="gate-review-body"):
                with VerticalScroll(classes=rail_classes):
                    yield from self._compose_gate_actions()
                    if self._settled_text is not None:
                        yield Static(
                            self._settled_text,
                            id="plan-settled-banner",
                            classes="gate-review-settled",
                        )
                    if self.has_decisions:
                        yield Static(
                            self._decisions_header(),
                            id="plan-decisions-header",
                            classes="gate-review-section-title",
                        )
                        try:
                            sheet_rows: list[dict[str, Any]] = list(
                                self._decision_draft.sheet().get("rows", [])
                            )
                        except Exception:
                            sheet_rows = []
                        yield PlanDecisionRows(
                            sheet_rows,
                            self._decision_definitions,
                            id="plan-decision-rows",
                            classes="plan-decision-rows",
                        )
                    yield Static("Verdict", classes="gate-review-section-title")
                    yield GateBranchControls(
                        self._gate,
                        host_collected_properties=HOST_COLLECTED_PROPERTIES,
                        gate_keymaps=self._gate_keymaps,
                        id="plan-approval-branches",
                        classes="gate-branch-controls--stacked",
                    )
                    if self.has_decisions:
                        yield Static(
                            self._verdict_summary_text(),
                            id="plan-verdict-summary",
                            classes="gate-review-verdict-summary",
                        )

                review_scroll = VerticalScroll(
                    id="plan-approval-scroll",
                    classes="gate-review-document",
                )
                review_scroll.border_title = Text(os.path.basename(self._plan_file))
                with review_scroll:
                    syntax = markdown_document_syntax(self._display_content())
                    yield Static(syntax, id="plan-approval-content")

            yield Static(
                self._footer_text(),
                id="plan-approval-footer",
                classes="gate-review-footer",
            )

    def _footer_text(self) -> Text:
        """Return footer hints with the declared primary action emphasized."""
        try:
            badge = self._enter_badge()
        except Exception:
            badge = None
        return plan_approval_footer_text(
            self._gate,
            self._gate_keymaps,
            self.gate_action_hints(separator="="),
            has_decisions=self.has_decisions,
            enter_badge=badge,
        )

    def _gate_control_ids(self) -> list[str]:
        try:
            controls = self._mounted_action_controls()
            action_ids = [] if controls is None else controls.control_ids()
        except Exception:
            action_ids = []
        decision_ids: list[str] = []
        try:
            rows = self.query_one("#plan-decision-rows", PlanDecisionRows)
            decision_ids = rows.visible_control_ids()
        except Exception:
            if self.has_decisions:
                decision_ids = [
                    f"plan-decision-{index}"
                    for index in range(len(self._decision_definitions))
                ]
        try:
            branch = self.query_one(GateBranchControls)
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

            focused = self.screen.focused
            focused_id = focused.id if isinstance(focused, Widget) else None
            try:
                current = control_ids.index(focused_id or "")
            except ValueError:
                current = -1 if delta > 0 else 0
            target = control_ids[(current + delta) % len(control_ids)]
            self.query_one(f"#{target}").focus(scroll_visible=False)  # type: ignore[no-any-return]
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
            rows = self.query_one("#plan-decision-rows", PlanDecisionRows)
            rows.set_focused_index(index)
        except Exception:
            pass
        self._scroll_to_focused_decision()

    def _focused_decision_id(self) -> str | None:
        try:
            rows = self.query_one("#plan-decision-rows", PlanDecisionRows)
            return rows.focused_id
        except Exception:
            return None

    def _apply_draft_edit(self, func: Any) -> None:
        if self._settled_text is not None:
            try:
                self.notify("Settled elsewhere; submit is disabled", severity="warning")
            except Exception:
                pass
            return
        if not self.has_decisions:
            return
        func()
        if self._request_id is not None:
            _ESC_DRAFTS[self._request_id] = self._decision_draft.values()
        self._refresh_verdict_summary()
        self._scroll_to_focused_decision()

    def on_mount(self) -> None:
        self._sync_submission_block()
        # Cache callout spans once; never validate on keypress.
        content = (
            self._plan_content
            if self._plan_content is not None
            else self._read_plan_file()
        )
        tier = "epic" if self._default_choice == "epic" else "tale"
        try:
            self._callout_spans = cache_callout_spans(content, tier)
        except Exception:
            self._callout_spans = []
        if self._settled_text is not None:
            try:
                branch = self.query_one(GateBranchControls)
                branch.block_submission("Settled elsewhere; submit is disabled")
            except Exception:
                pass
            return
        if self._pending_approve_state is not None:
            state = self._pending_approve_state
            self._pending_approve_state = None
            self._push_approve_options(
                commit_plan=state.commit_plan,
                run_coder=state.run_coder,
                coder_prompt=state.coder_prompt,
                coder_model=state.coder_model,
                wait_spec=state.wait_spec,
                capacity=state.capacity,
                choice=state.choice,
            )
            return
        if self.has_decisions:
            try:
                self.query_one("#plan-decision-0").focus(scroll_visible=False)
                try:
                    rows = self.query_one("#plan-decision-rows", PlanDecisionRows)
                    rows.set_focused_index(0)
                except Exception:
                    pass
                self._scroll_to_focused_decision()
                return
            except Exception:
                pass
        self.focus_gate_control(1)

    def render_reviewed_content(self, content: str) -> None:
        """Re-render the plan pane in place after an accepted edit action."""
        self._plan_content = content
        tier = "epic" if self._default_choice == "epic" else "tale"
        try:
            self._callout_spans = cache_callout_spans(content, tier)
        except Exception:
            self._callout_spans = []
        folded, fold_map, _line, _count = fold_plan_decisions_content(content)
        self._fold_map = fold_map
        try:
            self.query_one("#plan-approval-content", Static).update(
                markdown_document_syntax(folded if fold_map else content)
            )
        except Exception:
            pass

    def _read_plan_file(self) -> str:
        """Read the plan file content."""
        expanded = os.path.expanduser(self._plan_file)
        try:
            with open(expanded, encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"[Error reading plan file: {e}]"

    def _decision_inputs_for(
        self, selected_option_ids: tuple[str, ...]
    ) -> dict[str, dict[str, Any]]:
        if not self.has_decisions:
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
        self.dismiss(
            self._result_with_decisions(plan_approval_result_for_choice("approve"))
        )  # type: ignore[attr-defined]

    def action_tale(self) -> None:  # type: ignore[override]
        from .plan_approval_results import plan_approval_result_for_choice

        if not self._choice_allowed("tale"):  # type: ignore[attr-defined]
            return
        self.dismiss(
            self._result_with_decisions(plan_approval_result_for_choice("tale"))
        )  # type: ignore[attr-defined]

    def action_epic(self) -> None:  # type: ignore[override]
        from .plan_approval_results import plan_approval_result_for_choice

        if not self._choice_allowed("epic"):  # type: ignore[attr-defined]
            return
        self.dismiss(
            self._result_with_decisions(plan_approval_result_for_choice("epic"))
        )  # type: ignore[attr-defined]

    def action_reject(self) -> None:  # type: ignore[override]
        result = PlanApprovalResult(action="reject")
        result.review_revision = self._review_revision
        self.dismiss(result)  # type: ignore[attr-defined]

    def action_feedback(self) -> None:  # type: ignore[override]
        # Attach hidden sheet values via feedback_requested; the host
        # threads carries + decision values through PlanFeedbackContext.
        result = PlanApprovalResult(action="feedback_requested")
        result.review_revision = self._review_revision
        if self.has_decisions:
            decision_inputs = build_decision_option_inputs(
                self._gate, ("feedback",), self._decision_draft.decision_map()
            )
            if decision_inputs.get("feedback"):
                result.option_inputs = decision_inputs
        self.dismiss(result)  # type: ignore[attr-defined]

    def _result_with_decisions(self, result: PlanApprovalResult) -> PlanApprovalResult:
        if not self.has_decisions:
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
                self.notify("Settled elsewhere; submit is disabled", severity="warning")
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

    def action_scroll_down(self) -> None:
        """Scroll the content down by half a page."""
        scroll = self.query_one("#plan-approval-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def action_scroll_up(self) -> None:
        """Scroll the content up by half a page."""
        scroll = self.query_one("#plan-approval-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

    def action_scroll_to_top(self) -> None:
        """Scroll the content to the very top."""
        scroll = self.query_one("#plan-approval-scroll", VerticalScroll)
        scroll.scroll_home(animate=False)

    def action_scroll_to_bottom(self) -> None:
        """Scroll the content to the very bottom."""
        scroll = self.query_one("#plan-approval-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)

    def action_cancel(self) -> None:
        """Cancel the modal (no response written)."""
        if self._request_id is not None and self.has_decisions:
            _ESC_DRAFTS[self._request_id] = self._decision_draft.values()
        self.dismiss(None)

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

            focused = self.screen.focused
            focused_id = focused.id if isinstance(focused, Widget) else None
        except Exception:
            focused_id = None
        if focused_id is not None and focused_id.startswith("plan-decision-"):
            decision_id = self._focused_decision_id()
            if decision_id is not None:
                self._apply_draft_edit(lambda: self._decision_draft.flip(decision_id))
            return
        self.query_one(GateBranchControls).toggle_focused_option()

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
        self.query_one(GateBranchControls).submit_primary_branch()

    def action_submit_branch(self) -> None:
        self.query_one(GateBranchControls).submit_active_branch()

    def action_submit_numbered_branch(self, branch_index: int) -> None:
        self.query_one(GateBranchControls).submit_numbered_branch(branch_index)

    def action_open_inputs(self) -> None:
        self.query_one(GateBranchControls).open_inputs_for_focused_control()

    def action_copy_plan(self) -> None:
        """Copy the plan file contents to clipboard."""

        def content() -> str:
            value = (
                self._plan_content
                if self._plan_content is not None
                else self._read_plan_file()
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
        if "Decisions are fixed for this review" in message:
            try:
                self.notify(
                    message, title="Draft not accepted", severity="error", timeout=15
                )  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        super()._apply_edit_outcome(operation_id, outcome)  # type: ignore[misc]
