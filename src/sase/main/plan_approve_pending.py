"""Live-gate ``sase plan approve`` execution.

Runs (or previews with ``--dry-run``) the existing gate response path for
a pending plan proposal, including frozen Plan Decisions handling.
"""

from __future__ import annotations

from sase.main._plan_approve_shared import RenderedSelectionError
from sase.main.plan_pending import (
    PendingPlan,
    ensure_plan_notification_available,
    plan_context_from_notification,
)
from sase.plan_approval_actions import (
    PlanApprovalActionError,
    PlanApprovalActionResult,
    execute_plan_approval_response,
)

__all__ = ["approve_pending_plan"]


def approve_pending_plan(
    plan: PendingPlan,
    *,
    selector: str | None,
    kind: str | None,
    coder_prompt: str | None,
    coder_model: str | None,
    wait: str | None,
    dry_run: bool,
    project: str | None,
    decide: tuple[str, ...] = (),
) -> PlanApprovalActionResult | None:
    """Run or preview the existing gate response path."""
    if project:
        raise PlanApprovalActionError(
            "invalid_request",
            "project",
            "-P/--project only applies to plans without a live approval gate",
        )
    if plan.tier == "epic" and kind is None:
        from sase.main.plan_direct_approval import (
            DirectApprovalRefusal,
            DirectApprovalRefused,
        )

        displayed = selector or plan.display_name
        raise DirectApprovalRefused(
            DirectApprovalRefusal(
                code="epic_guard",
                header=f"✗ {plan.display_name} is an epic plan",
                detail_lines=(
                    f"Approve it as an epic:        sase plan approve {displayed} -k epic",
                    f"Or run it as a single tale:   sase plan approve {displayed} -k tale",
                ),
            )
        )
    selected_kind = kind or "tale"
    notification = plan.notification
    ensure_plan_notification_available(notification)
    from sase.main.plan_decide import parse_decide_assignments

    raw_map = parse_decide_assignments(list(decide or ()))
    decision_context = _live_decision_context(plan, raw_map)
    if dry_run:
        from sase.main.plan_approve_render import render_gate_approval_dry_run
        from sase._plan_approval_protocol import resolve_plan_approval_choice

        resolve_plan_approval_choice(notification.files[0], selected_kind)
        render_gate_approval_dry_run(
            plan,
            selected_kind,
            decision_lines=decision_context.card_lines(
                kind_label=selected_kind,
                plan_name=plan.display_name,
                dry_run=True,
            ),
        )
        return None
    option_inputs: dict[str, dict[str, object]] | None = None
    if decision_context.has_decisions:
        try:
            from sase._plan_approval_protocol import resolve_plan_approval_choice
            from sase.plan_approval_choices import plan_approval_selection_for_choice

            resolved_choice = resolve_plan_approval_choice(
                notification.files[0], selected_kind
            )
            selected_options = plan_approval_selection_for_choice(
                resolved_choice, tier="epic" if plan.tier == "epic" else "tale"
            )
        except (KeyError, ValueError):
            # The executor raises the authoritative selection error itself;
            # submit no decision inputs so its verdict is unchanged.
            selected_options = ()
            resolved_choice = selected_kind
        option_inputs = decision_context.option_inputs_for(
            resolved_choice=resolved_choice,
            selected=selected_options,
        )
    try:
        result = execute_plan_approval_response(
            plan_context_from_notification(notification),
            selected_kind,
            coder_prompt=coder_prompt,
            coder_model=coder_model,
            wait=wait,
            epic_launch_mode="launch",
            epic_launch_origin="cli",
            option_inputs=option_inputs,
            expected_review_revision=decision_context.review_revision,
            source="cli",
        )
    except PlanApprovalActionError as exc:
        if getattr(exc, "code", "") == "stale_review":
            raise _rendered_stale_review_error(plan) from exc
        raise
    from sase.main.plan_approve_render import render_gate_approval

    render_gate_approval(
        plan,
        result,
        decision_lines=decision_context.card_lines(
            kind_label=selected_kind,
            plan_name=plan.display_name,
            dry_run=False,
        ),
    )
    return result


class _LiveDecisionContext:
    """Frozen decision definitions, answers, and card for one live gate."""

    def __init__(
        self,
        *,
        definitions: list[dict[str, object]],
        review_revision: int | None,
        values: dict[str, object],
        rows: list[dict[str, object]],
        sheet: dict[str, object] | None,
        declaring_options: set[str],
        tier: str,
    ) -> None:
        self.definitions = definitions
        self.review_revision = review_revision
        self.values = values
        self.rows = rows
        self.sheet = sheet
        self.declaring_options = declaring_options
        self.tier = tier

    @property
    def has_decisions(self) -> bool:
        """Whether the live gate froze any Plan Decisions."""
        return bool(self.definitions)

    def option_inputs_for(
        self,
        *,
        resolved_choice: str,
        selected: tuple[str, ...],
    ) -> dict[str, dict[str, object]] | None:
        """Build per-option ``decision_*`` inputs for resolved options."""
        del resolved_choice
        if not self.has_decisions:
            return None
        if not self.values and not self.rows:
            return None
        payload = {
            f"decision_{decision_id}": value
            for decision_id, value in self.values.items()
        }
        inputs: dict[str, dict[str, object]] = {}
        for option_id in selected:
            if option_id in self.declaring_options:
                inputs[option_id] = dict(payload)
        return inputs or None

    def card_lines(
        self,
        *,
        kind_label: str,
        plan_name: str,
        dry_run: bool,
    ) -> list[str] | None:
        """Render the Section 1.4 card, or ``None`` without decisions."""
        if not self.has_decisions or self.sheet is None:
            return None
        from sase.main.plan_decide import decision_card_lines, verdict_for_kind

        return decision_card_lines(
            kind_label=kind_label,
            plan_name=plan_name,
            review_revision=self.review_revision or 0,
            sheet=self.sheet,
            rows=self.rows,
            verdict=verdict_for_kind(
                "epic" if self.tier == "epic" and kind_label == "epic" else kind_label
            ),
            dry_run=dry_run,
        )


def _live_decision_context(
    plan: PendingPlan, raw_map: dict[str, str]
) -> _LiveDecisionContext:
    """Freeze ``-D`` answers against the live gate before any side effect."""
    from sase.main.plan_decide import DecideError, caller_for_decide

    tier = "epic" if plan.tier == "epic" else "tale"
    definitions, review_revision, declaring = _live_gate_decisions(plan)
    if not definitions:
        if raw_map:
            raise DecideError(
                f"✗ {plan.display_name} has no decisions; "
                f"-D {next(iter(raw_map))} matches nothing.",
            )
        return _LiveDecisionContext(
            definitions=[],
            review_revision=None,
            values={},
            rows=[],
            sheet=None,
            declaring_options=set(),
            tier=tier,
        )
    from sase.main.plan_decide import resolve_decide_values

    values, rows = resolve_decide_values(
        definitions, raw_map, caller=caller_for_decide()
    )
    from sase.sdd.plan_decisions import sheet_binding

    try:
        sheet: dict[str, object] | None = sheet_binding(
            definitions, values, review_revision
        )
    except Exception as exc:
        raise DecideError(
            f"✗ plan decisions failed to resolve: {exc}",
        ) from exc
    return _LiveDecisionContext(
        definitions=definitions,
        review_revision=review_revision,
        values=values,
        rows=rows,
        sheet=sheet,
        declaring_options=declaring,
        tier=tier,
    )


def _live_gate_decisions(
    plan: PendingPlan,
) -> tuple[list[dict[str, object]], int, set[str]]:
    """Read frozen ``payload.decisions`` and the revision from the bundle."""
    try:
        from sase.notification_gates.hashing import load_and_verify_bundle
        from sase.notification_gates.paths import resolve_action_bundle
    except Exception:
        return [], 0, set()
    try:
        action = "EpicApproval" if plan.tier == "epic" else "PlanApproval"
        bundle = resolve_action_bundle(action, plan.notification.action_data)
        if bundle is None:
            return [], 0, set()
        envelope, _adapter = load_and_verify_bundle(bundle.root)
    except Exception:
        return [], 0, set()
    payload = envelope.get("payload")
    definitions = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(definitions, list):
        return [], 0, set()
    try:
        review_revision = int(envelope.get("review_revision", 1))
    except (TypeError, ValueError):
        review_revision = 1
    declaring: set[str] = set()
    raw_options = envelope.get("options")
    if isinstance(raw_options, list):
        for raw in raw_options:
            if not isinstance(raw, dict):
                continue
            option_id = raw.get("id")
            schema = raw.get("input_schema")
            props = schema.get("properties") if isinstance(schema, dict) else None
            if not isinstance(option_id, str) or not isinstance(props, dict):
                continue
            if any(str(name).startswith("decision_") for name in props):
                declaring.add(option_id)
    return (
        [item for item in definitions if isinstance(item, dict)],
        review_revision,
        declaring,
    )


def _rendered_stale_review_error(plan: PendingPlan) -> PlanApprovalActionError:
    """Explain a revision mismatch with a refresh path (contract 5)."""
    return RenderedSelectionError(
        "stale_review",
        plan.display_name,
        "this review changed since it was shown; "
        "re-run `sase plan show` for the current revision and approve again",
    )
