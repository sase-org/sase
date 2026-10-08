"""Plan approval modal for sase's TUI.

This module owns the modal itself: its layout, its scrolling and copy
shortcuts, and how it is wired to the shared gate machinery. The pieces that
are not about the screen live beside it — the branch model defaults in
:mod:`~sase.ace.tui.modals.plan_approval_gate_data`, the result protocol in
:mod:`~sase.ace.tui.modals.plan_approval_results`, the decision handling in
:mod:`~sase.ace.tui.modals.plan_approval_decisions`, and the hint line in
:mod:`~sase.ace.tui.modals.plan_approval_footer`.

The modal class below is a thin shell: rendering and verdict display come
from :mod:`~sase.ace.tui.modals.plan_approval_modal_view`, focus and
submission behavior from
:mod:`~sase.ace.tui.modals.plan_approval_modal_controls`, and the shared
Esc-draft store from
:mod:`~sase.ace.tui.modals._plan_approval_modal_state`. The public names
(``PlanApprovalModal``, ``PlanApprovalResult``, ``PendingApproveState``,
``PlanApprovalChoice``) keep their import path from this module.
"""

from __future__ import annotations

from typing import Any

from textual.binding import BindingsMap
from textual.screen import ModalScreen

from sase.notification_gates.debug import GateDebugContext

from ..keymaps import (
    GateModalKeymaps,
    build_gate_modal_bindings,
    build_gate_numbered_branch_bindings,
)
from ._plan_approval_modal_state import esc_drafts
from .base import CopyModeForwardingMixin
from .gate_action_controls import GateActionsData
from .gate_action_runner import (
    GateActionRunner,
    GateActionsMixin,
    gate_modal_taken_keys,
)
from .gate_branch_controls import GateBranchData
from .plan_approval_decisions import PlanApprovalDecisionsMixin
from .plan_approval_gate_data import (
    DEFAULT_GATE_KEYMAPS,
    PLAN_GATE_STATIC_BINDINGS,
    default_plan_gate_data,
)
from .plan_approval_modal_controls import PlanApprovalControlsMixin
from .plan_approval_modal_view import PlanApprovalViewMixin
from .plan_approval_results import (
    PendingApproveState,
    PlanApprovalChoice,
    PlanApprovalResult,
)
from .plan_decision_sheet import PlanDecisionDraft


class PlanApprovalModal(
    PlanApprovalViewMixin,
    PlanApprovalControlsMixin,
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
        if request_id is not None and request_id in esc_drafts:
            restored = esc_drafts.get(request_id)
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
