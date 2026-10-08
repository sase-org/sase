"""Read-only resolver for gateless ``sase plan approve`` runs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.main._plan_direct_approval_shared import plan_stem
from sase.main.plan_direct_approval_lookup import (
    authored_tier,
    classify_location,
    committed_plan_ref,
    predicted_plan_ref,
    validation_size,
)
from sase.main.plan_direct_approval_placement import (
    resolve_bead,
    resolve_model_directive,
    resolve_placement,
)
from sase.main.plan_direct_approval_project import (
    project_tag_for,
    resolve_planner,
    resolve_project,
)
from sase.main.plan_direct_approval_prompt import compose_coder_prompt
from sase.main.plan_direct_approval_types import (
    CoderPlacement,
    DirectApprovalKind,
    DirectApprovalLocation,
    DirectApprovalPlan,
    DirectApprovalRefusal,
    DirectApprovalRequest,
    RetiredGate,
    RetiredGateState,
)

if TYPE_CHECKING:
    from sase.main.plan_direct_approval_recovery import CoderRecovery, PriorCoder
    from sase.main.plan_pending_diagnosis import PlanGateHistory


def resolve_direct_approval(
    request: DirectApprovalRequest,
) -> DirectApprovalPlan | DirectApprovalRefusal | None:
    """Resolve *request* to a plan, refusal, or ``None`` (no plan file)."""
    from sase.main.plan_pending_diagnosis import classify_plan_gate_history
    from sase.main.plan_pending_diagnosis import locate_plan_candidates

    candidates = locate_plan_candidates(request.selector)
    if not candidates:
        return None
    if len(candidates) > 1:
        names = ", ".join(sorted(str(path) for path in candidates))
        return DirectApprovalRefusal(
            code="ambiguous",
            header=f"{request.selector.strip()} matches more than one plan",
            detail_lines=(names,),
            hints=(f"sase plan approve {candidates[0]}",),
        )
    source_path = candidates[0]
    location = classify_location(source_path, request.cwd)
    name = plan_stem(source_path)

    from sase.main.plan_inventory_paths import plan_metadata_for_path

    metadata = plan_metadata_for_path(str(source_path))
    title = metadata.title or name

    kind: DirectApprovalKind = request.kind or "tale"

    if location == "committed" and kind in ("tale", "commit"):
        ref = committed_plan_ref(source_path)
        detail = (
            f"{name} is already committed as {ref}"
            if ref
            else f"{name} is already committed"
        )
        return DirectApprovalRefusal(
            code="already_committed",
            header=f"\u2717 {detail}",
            detail_lines=(
                "A committed tale is already approved. To run another coder on it:",
            ),
            hints=(f"sase run '#coder({source_path})'",),
        )

    # Validation: always as a tale. Raises PlanApprovalValidationError.
    from sase.plan_approval_actions import require_plan_approval_validation

    validation = require_plan_approval_validation(source_path, "tale")
    size = validation_size(validation)

    from sase.main.plan_decide import (
        already_approved_decide_error,
        caller_for_decide,
        parse_decide_assignments,
        resolve_direct_decisions,
    )

    raw_map = parse_decide_assignments(list(request.decide or ()))
    caller = caller_for_decide()

    history = classify_plan_gate_history(source_path)
    if raw_map and getattr(history, "kind", "none") in ("direct", "handled"):
        raise already_approved_decide_error(raw_map)
    gate = _retired_gate_from_history(history)
    planner = resolve_planner(source_path, history)
    project_refusal_or_name = resolve_project(request, source_path, history, planner)
    if isinstance(project_refusal_or_name, DirectApprovalRefusal):
        return project_refusal_or_name
    project = project_refusal_or_name
    project_tag = project_tag_for(project)

    recovered = _resolve_recovery(
        request,
        source_path,
        location,
        name,
        title,
        size,
        history,
        planner,
        project,
        project_tag,
    )
    if recovered is not None:
        if (
            raw_map
            and isinstance(recovered, DirectApprovalPlan)
            and recovered.recovery is not None
        ):
            raise already_approved_decide_error(raw_map)
        return recovered

    handled_refusal = _handled_refusal(request, source_path, name, title, history)
    if handled_refusal is not None:
        return handled_refusal

    # Epic-guard and gateless-epic refusals need the authored tier.
    tier = authored_tier(source_path)
    if tier == "epic" and not request.kind_explicit:
        return DirectApprovalRefusal(
            code="epic_guard",
            header=f"\u2717 {name} is an epic plan",
            detail_lines=(
                f"Approve it as an epic:        sase plan approve {request.selector.strip()} -k epic",
                f"Or run it as a single tale:   sase plan approve {request.selector.strip()} -k tale",
            ),
            hints=(
                f"sase plan approve {request.selector.strip()} -k epic",
                f"sase plan approve {request.selector.strip()} -k tale",
            ),
        )
    if kind == "epic":
        return DirectApprovalRefusal(
            code="epic_without_gate",
            header=f"\u2717 {name} is an epic plan without a live approval gate",
            detail_lines=(
                f"Launch it with:               sase bead work {source_path}",
                f"Or run it as a single tale:   sase plan approve {request.selector.strip()} -k tale",
            ),
            hints=(
                f"sase bead work {source_path}",
                f"sase plan approve {request.selector.strip()} -k tale",
            ),
        )

    placement = resolve_placement(planner, project, history, plan_name=name)
    if isinstance(placement, DirectApprovalRefusal):
        return placement

    decided = resolve_direct_decisions(validation, raw_map, caller=caller)
    decide_values: dict[str, object] = dict(decided[0]) if decided else {}
    decide_rows: tuple[dict[str, object], ...] = tuple(decided[1]) if decided else ()
    decide_sheet: dict[str, object] | None = decided[2] if decided else None
    decide_definitions: tuple[dict[str, object], ...] = ()
    if decided:
        try:
            from sase.sdd.plan_decisions import (
                artifacts_dir_from_env,
                build_definitions,
            )

            decide_definitions = tuple(
                dict(item)
                for item in build_definitions(validation, artifacts_dir_from_env())
            )
        except Exception:
            decide_definitions = ()

    model_directive = resolve_model_directive(
        source_path, request.coder_model, request.coder_prompt
    )
    bead = resolve_bead(source_path, placement, project)
    predicted_ref = predicted_plan_ref(source_path, kind, location)
    wait_spec = _parse_wait(request.wait)
    prompt_preview = compose_coder_prompt(
        project_tag=project_tag,
        model_directive=model_directive,
        plan_argument=predicted_ref or str(source_path),
        extra_prompt=request.coder_prompt,
        wait=wait_spec,
        bead=bead,
        placement=placement,
    )
    return DirectApprovalPlan(
        request=request,
        kind=kind,
        source_path=source_path,
        location=location,
        name=name,
        title=title,
        size=size,
        project=project,
        project_tag=project_tag,
        planner=planner,
        gate=gate,
        placement=placement,
        model_directive=model_directive,
        bead=bead,
        predicted_plan_ref=predicted_ref,
        coder_prompt_preview=prompt_preview,
        decide_values=decide_values,
        decide_rows=decide_rows,
        decide_sheet=decide_sheet,
        decide_definitions=decide_definitions,
    )


def _resolve_recovery(
    request: DirectApprovalRequest,
    source_path: Path,
    location: DirectApprovalLocation,
    name: str,
    title: str | None,
    size: str | None,
    history: PlanGateHistory,
    planner: str | None,
    project: str,
    project_tag: str,
) -> DirectApprovalPlan | DirectApprovalRefusal | None:
    """Return a recovery plan, a coder-state refusal, or ``None``.

    ``None`` means the history is not an approval that owed a coder (or the
    requested kind is not a coder kind), so the caller keeps today's refusal.
    """
    from sase.main.plan_direct_approval_recovery import evaluate_approval_recovery

    effective_kind = request.kind or "tale"
    if effective_kind not in ("tale", "approve"):
        return None
    recovery = evaluate_approval_recovery(
        local_plan=source_path,
        history=history,
        project=project,
        cwd=request.cwd,
    )
    if recovery is None:
        return None
    if recovery.verdict == "live":
        return coder_running_refusal(name, title or name, recovery)
    placement = resolve_placement(
        planner, project, history, plan_name=name, recovery=True
    )
    if isinstance(placement, DirectApprovalRefusal):
        placement = CoderPlacement(
            mode="standalone",
            parent=planner,
            reason="agent session lookup failed",
        )
    model_directive = resolve_model_directive(
        source_path, request.coder_model, request.coder_prompt
    )
    bead = resolve_bead(source_path, placement, project)
    wait_spec = _parse_wait(request.wait)
    prompt = compose_coder_prompt(
        project_tag=project_tag,
        model_directive=model_directive,
        plan_argument=recovery.plan_argument or str(source_path),
        extra_prompt=request.coder_prompt,
        wait=wait_spec,
        bead=bead,
        placement=placement,
    )
    if recovery.verdict == "succeeded":
        return already_implemented_refusal(name, title or name, recovery, prompt)
    from typing import cast

    return DirectApprovalPlan(
        request=request,
        kind=cast(DirectApprovalKind, effective_kind),
        source_path=source_path,
        location=location,
        name=name,
        title=title,
        size=size,
        project=project,
        project_tag=project_tag,
        planner=planner,
        gate=_retired_gate_from_history(history),
        placement=placement,
        model_directive=model_directive,
        bead=bead,
        predicted_plan_ref=recovery.plan_argument or str(source_path),
        coder_prompt_preview=prompt,
        recovery=recovery,
    )


def _recovery_plan_bit(recovery: CoderRecovery) -> str:
    age = f" {recovery.approved_age}" if recovery.approved_age else ""
    return f"{recovery.plan_argument} · approved as a {recovery.approved_action}{age}"


def _recovery_display_prior(recovery: CoderRecovery, want: str) -> PriorCoder | None:
    for prior in recovery.prior_coders:
        if prior.state == want:
            return prior
    return recovery.prior_coders[0] if recovery.prior_coders else None


def coder_running_refusal(
    name: str, title: str, recovery: CoderRecovery
) -> DirectApprovalRefusal:
    from sase.main.plan_direct_approval_recovery import prior_coder_word

    prior = _recovery_display_prior(recovery, "live")
    if prior is None:
        coder_bit = "coder   none found"
        hints: tuple[str, ...] = ("sase agent list",)
    else:
        coder_bit = f"coder   {prior.name} · {prior_coder_word(prior)}"
        hints = (f"sase agent show {prior.name}",)
    return DirectApprovalRefusal(
        code="coder_running",
        header=f"{name} is already approved and its coder is running",
        detail_lines=(title, _recovery_plan_bit(recovery), coder_bit),
        hints=hints,
    )


def already_implemented_refusal(
    name: str, title: str, recovery: CoderRecovery, prompt: str
) -> DirectApprovalRefusal:
    import shlex

    from sase.main.plan_direct_approval_recovery import prior_coder_word

    prior = _recovery_display_prior(recovery, "succeeded")
    if prior is None:
        coder_bit = "plan status is done"
    else:
        coder_bit = f"coder   {prior.name} · {prior_coder_word(prior)}"
    return DirectApprovalRefusal(
        code="already_implemented",
        header=f"{name} is already approved and implemented",
        detail_lines=(
            title,
            _recovery_plan_bit(recovery),
            coder_bit,
            "To run another coder anyway:",
        ),
        hints=(f"sase run {shlex.quote(prompt)}",),
    )


def _handled_refusal(
    request: DirectApprovalRequest,
    source_path: Path,
    name: str,
    title: str,
    history: PlanGateHistory,
) -> DirectApprovalRefusal | None:
    kind = getattr(history, "kind", "none")
    if kind == "direct":
        from sase.main.plan_pending_diagnosis import (
            direct_approval_via_text,
            inspect_command_for_located_plan,
        )

        action = getattr(history, "action", None) or "tale"
        age = getattr(history, "age", "") or ""
        try:
            from sase.plan_approval_receipts import read_direct_approval_receipt

            receipt = read_direct_approval_receipt(source_path)
            coder = receipt.coder_agent if receipt is not None else None
        except Exception:
            coder = None
        coder_bit = f" \u00b7 coder {coder}" if coder else ""
        via = direct_approval_via_text(source_path)
        inspect_command = inspect_command_for_located_plan(source_path, history)
        return DirectApprovalRefusal(
            code="already_approved",
            header=f"{name} is not awaiting approval",
            detail_lines=(
                f"{title}",
                f"{source_path}",
                f"This plan was already approved as a {action} {via}{age}{coder_bit}.",
                f"Inspect it with: {inspect_command}",
            ),
            hints=(inspect_command,),
        )
    if kind == "handled":
        from sase.main.plan_pending_diagnosis import (
            diagnose_located_plan_miss,
            inspect_command_for_located_plan,
        )

        miss = diagnose_located_plan_miss(request.selector, source_path)
        return DirectApprovalRefusal(
            code="conflict_already_handled",
            header=miss.header,
            detail_lines=miss.detail_lines,
            hints=(inspect_command_for_located_plan(source_path, history),),
        )
    return None


def _retired_gate_from_history(history: object) -> RetiredGate | None:
    kind = getattr(history, "kind", "none")
    if kind != "orphaned" and kind != "expired":
        return None
    notification_id = getattr(history, "notification_id", None)
    if not isinstance(notification_id, str) or not notification_id.strip():
        return None
    state: RetiredGateState = "orphaned" if kind == "orphaned" else "expired"
    return RetiredGate(
        notification_id=notification_id.strip(),
        state=state,
        bundle_path=getattr(history, "bundle_path", None),
        action_data=getattr(history, "action_data", None),
    )


def _parse_wait(wait: object) -> object:
    if wait is None:
        return None
    from sase._plan_approval_response import parse_plan_approval_wait

    if isinstance(wait, str):
        return parse_plan_approval_wait(wait or None)
    return wait


__all__ = [
    "already_implemented_refusal",
    "coder_running_refusal",
    "resolve_direct_approval",
]
