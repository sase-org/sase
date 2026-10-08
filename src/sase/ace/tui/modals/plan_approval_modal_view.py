"""Layout, verdict display, and document-pane behavior for the plan modal.

This mixin owns everything
:class:`~sase.ace.tui.modals.plan_approval_modal.PlanApprovalModal` shows: the
title badge, the verdict summary, ``compose`` itself, the footer hint line, and
scrolling the review document. Submission, focus movement, and clipboard
actions live in
:mod:`~sase.ace.tui.modals.plan_approval_modal_controls`.
"""

from __future__ import annotations

import os
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from ..keymaps import GateModalKeymaps
from ..util.frontmatter_syntax import markdown_document_syntax
from .gate_branch_controls import GateBranchControls, GateBranchData
from .plan_approval_footer import plan_approval_footer_text
from .plan_approval_gate_data import HOST_COLLECTED_PROPERTIES
from .plan_approval_results import PlanApprovalChoice
from .plan_decision_document import (
    cache_callout_spans,
    fold_plan_decisions_content,
    scroll_target_for_decision,
)
from .plan_decision_rows import PlanDecisionRows
from .plan_decision_sheet import PlanDecisionDraft, verdict_for_selection

__all__ = ["PlanApprovalViewMixin"]


def _provider_badge_markup(llm_provider: str | None, model: str | None) -> str:
    """Render a Rich-markup badge like ``CLAUDE(opus)`` with provider theming.

    Returns an empty string when neither field is set, so callers can collapse
    the title to its unbadged form.
    """
    from sase.ace.tui.provider_styles import provider_model_badge_markup

    return provider_model_badge_markup(llm_provider, model)


def _short_verdict_label(epic: bool, commit_plan: bool, run_coder: bool) -> str:
    if epic:
        return "Epic"
    if commit_plan and run_coder:
        return "Tale"
    if run_coder:
        return "Coder"
    return "Commit"


class PlanApprovalViewMixin:
    """Render the plan review modal and its verdict displays."""

    _gate: GateBranchData
    _llm_provider: str | None
    _model: str | None
    _default_choice: PlanApprovalChoice
    _plan_file: str
    _plan_content: str | None
    _settled_text: str | None
    _gate_keymaps: GateModalKeymaps
    _decision_definitions: list[dict[str, Any]]
    _decision_draft: PlanDecisionDraft
    _fold_map: dict[int, int]
    _callout_spans: list[dict[str, Any]]

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
            controls = self.query_one(GateBranchControls)  # type: ignore[attr-defined]
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
            controls = self.query_one(GateBranchControls)  # type: ignore[attr-defined]
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
        if not self.has_decisions:  # type: ignore[attr-defined]
            return primary_action_badge_for_label(
                label, self._gate_keymaps.submit_primary
            )
        verdict = verdict_for_selection(commit_plan=commit, run_coder=run, epic=epic)
        short = self._decision_draft.short_summary(verdict)
        return primary_action_badge_for_label(
            f"{label} · {short}", self._gate_keymaps.submit_primary
        )

    def _verdict_summary_text(self) -> Text:
        if not self.has_decisions:  # type: ignore[attr-defined]
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
        if not self.is_mounted:  # type: ignore[attr-defined]
            return
        try:
            summary = self.query_one("#plan-verdict-summary", Static)  # type: ignore[attr-defined]
            summary.update(self._verdict_summary_text())
        except Exception:
            pass
        try:
            footer = self.query_one("#plan-approval-footer", Static)  # type: ignore[attr-defined]
            footer.update(self._footer_text())
        except Exception:
            pass
        try:
            rows = self.query_one("#plan-decision-rows", PlanDecisionRows)  # type: ignore[attr-defined]
            rows.update_rows(self._decision_draft.sheet().get("rows", []))
        except Exception:
            pass

    def _scroll_to_focused_decision(self) -> None:
        if not self.has_decisions or not self.is_mounted:  # type: ignore[attr-defined]
            return
        try:
            rows = self.query_one("#plan-decision-rows", PlanDecisionRows)  # type: ignore[attr-defined]
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
            scroll = self.query_one("#plan-approval-scroll", VerticalScroll)  # type: ignore[attr-defined]
            scroll.scroll_to(y=target, animate=False)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        rail_classes = "gate-review-actions"
        if self.has_decisions:  # type: ignore[attr-defined]
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
                    yield from self._compose_gate_actions()  # type: ignore[attr-defined]
                    if self._settled_text is not None:
                        yield Static(
                            self._settled_text,
                            id="plan-settled-banner",
                            classes="gate-review-settled",
                        )
                    if self.has_decisions:  # type: ignore[attr-defined]
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
                    if self.has_decisions:  # type: ignore[attr-defined]
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
            self.gate_action_hints(separator="="),  # type: ignore[attr-defined]
            has_decisions=self.has_decisions,  # type: ignore[attr-defined]
            enter_badge=badge,
        )

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
            self.query_one("#plan-approval-content", Static).update(  # type: ignore[attr-defined]
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

    def action_scroll_down(self) -> None:
        """Scroll the content down by half a page."""
        scroll = self.query_one("#plan-approval-scroll", VerticalScroll)  # type: ignore[attr-defined]
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def action_scroll_up(self) -> None:
        """Scroll the content up by half a page."""
        scroll = self.query_one("#plan-approval-scroll", VerticalScroll)  # type: ignore[attr-defined]
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

    def action_scroll_to_top(self) -> None:
        """Scroll the content to the very top."""
        scroll = self.query_one("#plan-approval-scroll", VerticalScroll)  # type: ignore[attr-defined]
        scroll.scroll_home(animate=False)

    def action_scroll_to_bottom(self) -> None:
        """Scroll the content to the very bottom."""
        scroll = self.query_one("#plan-approval-scroll", VerticalScroll)  # type: ignore[attr-defined]
        scroll.scroll_end(animate=False)
