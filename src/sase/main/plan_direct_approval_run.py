"""Executor for gateless ``sase plan approve`` runs.

Follows the eight-step order from the epic plan: validate/resolve (read-only,
in the resolver), adopt, re-check receipt, archive, write receipt, retire
gate, launch coder, rewrite receipt, record planner metadata.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sase.main.plan_direct_approval import (
    DirectApprovalPlan,
    DirectApprovalRefusal,
    DirectApprovalRefused,
    compose_coder_prompt,
)

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult


@dataclass
class DirectApprovalOutcome:
    """Result of one executed direct approval."""

    plan: DirectApprovalPlan
    local_plan_path: Path
    plan_ref: str
    saved_plan_path: str | None
    coder_prompt: str
    coder: AgentLaunchResult | None = None
    coder_error: str | None = None
    warnings: tuple[str, ...] = ()


def execute_direct_approval(plan: DirectApprovalPlan) -> DirectApprovalOutcome:
    """Execute a resolved direct approval through the eight-step order."""
    from sase._plan_approval_protocol import PlanApprovalActionError

    if os.environ.get("SASE_AGENT"):
        raise PlanApprovalActionError(
            "agent_launch_denied",
            plan.name,
            "plan approval launches agents and must be run by the user, "
            "not from inside a running SASE agent",
        )
    # 2. Adopt scratch plans into ~/.sase/plans, then re-check the receipt.
    local_plan = _adopt_plan(plan)
    _refuse_if_receipt(local_plan, plan)
    # 3. Publish to the SDD store for tale/commit.
    plan_ref, saved_plan = _archive_plan(plan, local_plan)
    # 4. Write the receipt with coder fields still empty.
    _write_receipt(plan, local_plan, plan_ref, saved_plan, coder=None, coder_error=None)
    # 5. Retire a stale or orphaned gate, all best-effort.
    warnings: list[str] = []
    _retire_gate(plan, warnings)
    # 6. Launch the coder for tale/approve.
    coder: AgentLaunchResult | None = None
    coder_error: str | None = None
    coder_prompt = ""
    if plan.kind in ("tale", "approve"):
        coder_prompt = compose_coder_prompt(
            project_tag=plan.project_tag,
            model_directive=plan.model_directive,
            plan_argument=plan_ref or str(local_plan),
            extra_prompt=plan.request.coder_prompt,
            wait=_request_wait(plan),
            bead=plan.bead,
            placement=plan.placement,
        )
        try:
            coder = _launch_coder(coder_prompt, local_plan)
        except Exception as exc:
            coder_error = str(exc) or type(exc).__name__
    else:
        coder_prompt = plan.coder_prompt_preview
    # 7. Rewrite the receipt with the coder outcome.
    _write_receipt(
        plan, local_plan, plan_ref, saved_plan, coder=coder, coder_error=coder_error
    )
    # 8. Record planner metadata, best-effort.
    _record_planner_metadata(plan, warnings)
    return DirectApprovalOutcome(
        plan=plan,
        local_plan_path=local_plan,
        plan_ref=plan_ref,
        saved_plan_path=saved_plan,
        coder_prompt=coder_prompt,
        coder=coder,
        coder_error=coder_error,
        warnings=tuple(warnings),
    )


def _adopt_plan(plan: DirectApprovalPlan) -> Path:
    if plan.location != "scratch":
        return plan.source_path.expanduser().resolve(strict=False)
    from sase.llm_provider._plan_utils import adopt_plan_into_sase

    return adopt_plan_into_sase(plan.source_path)


def _refuse_if_receipt(local_plan: Path, plan: DirectApprovalPlan) -> None:
    try:
        from sase.plan_approval_receipts import read_direct_approval_receipt
    except Exception:
        return
    try:
        receipt = read_direct_approval_receipt(local_plan)
    except Exception:
        return
    if receipt is None:
        return
    from sase._plan_approval_protocol import PlanApprovalActionError

    raise PlanApprovalActionError(
        "already_approved",
        plan.name,
        f"{plan.name} was already approved as a tale via sase plan approve"
        f" ({receipt.approved_at})",
    )


def _archive_plan(plan: DirectApprovalPlan, local_plan: Path) -> tuple[str, str | None]:
    if plan.kind == "approve":
        ref = plan.predicted_plan_ref or str(local_plan)
        return ref, None
    from sase._plan_approval_side_effects import preflight_plan_archive_credential
    from sase._plan_archive_approval import (
        PlanAlreadyArchivedError,
        archive_approved_plan,
    )
    from sase._plan_approval_protocol import PlanApprovalActionError

    preflight_plan_archive_credential(("commit",))
    try:
        archived = archive_approved_plan(
            {},
            local_plan,
            tier="tale",
            project_name=plan.project,
            if_exists="refuse",
        )
    except PlanAlreadyArchivedError as exc:
        raise PlanApprovalActionError(
            "already_committed", str(exc.path), str(exc)
        ) from exc
    return archived.plan_archive_ref, archived.saved_plan_path


def _write_receipt(
    plan: DirectApprovalPlan,
    local_plan: Path,
    plan_ref: str,
    saved_plan: str | None,
    *,
    coder: AgentLaunchResult | None,
    coder_error: str | None,
) -> None:
    from sase.plan_approval_receipts import (
        DirectApprovalReceipt,
        write_direct_approval_receipt,
    )

    route = (
        "none"
        if plan.kind == "commit"
        else ("family" if plan.placement.mode == "family" else "standalone")
    )
    receipt = DirectApprovalReceipt(
        plan_path=str(local_plan),
        action=plan.kind,
        approved_at=datetime.now(UTC).isoformat(),
        source="cli",
        route=route,
        project=plan.project,
        plan_archive_ref=plan_ref or None,
        saved_plan_path=saved_plan,
        coder_agent=getattr(coder, "agent_name", None) if coder is not None else None,
        coder_pid=getattr(coder, "pid", None) if coder is not None else None,
        coder_error=coder_error,
        family=plan.placement.family,
        retired_gate_id=plan.gate.notification_id if plan.gate is not None else None,
        original_path=str(plan.source_path),
    )
    write_direct_approval_receipt(receipt)


def _retire_gate(plan: DirectApprovalPlan, warnings: list[str]) -> None:
    gate = plan.gate
    if gate is None:
        return
    if gate.bundle_path is None:
        warnings.append(f"gate {gate.notification_id} has no bundle to retire")
        return
    try:
        from sase.notification_gates.executor_cancellation import cancel_gate
    except Exception as exc:
        warnings.append(f"gate {gate.notification_id} could not be retired: {exc}")
        return
    try:
        cancel_gate(gate.bundle_path, reason="approved_directly", source="plan_approve")
    except Exception as exc:
        if "already_answered" in type(exc).__name__ or "already_answered" in str(exc):
            warnings.append(
                f"gate {gate.notification_id} was answered concurrently;"
                " no second coder launched"
            )
            raise DirectApprovalRefused(
                DirectApprovalRefusal(
                    code="conflict_already_handled",
                    header=f"{plan.name} was already handled",
                    detail_lines=tuple(warnings),
                    hints=("sase plan list",),
                )
            ) from exc
        warnings.append(f"gate {gate.notification_id} could not be retired: {exc}")
        return
    try:
        from sase.notifications.pending_actions import mark_already_handled

        mark_already_handled(
            gate.notification_id, source="plan_approve", action=plan.kind
        )
    except Exception as exc:
        warnings.append(f"gate {gate.notification_id} could not be marked: {exc}")
    try:
        from sase.plan_approval_actions import dismiss_notification_best_effort

        dismiss_notification_best_effort(gate.notification_id)
    except Exception as exc:
        warnings.append(f"gate {gate.notification_id} could not be dismissed: {exc}")


def _launch_coder(prompt: str, local_plan: Path) -> AgentLaunchResult:
    from sase.agent.launch_cwd import launch_agents_from_cwd

    results = launch_agents_from_cwd(prompt, extra_env={"SASE_PLAN": str(local_plan)})
    if not results:
        raise RuntimeError("agent launch produced no results")
    return results[0]


def _request_wait(plan: DirectApprovalPlan) -> object:
    return plan.request.wait


def _record_planner_metadata(plan: DirectApprovalPlan, warnings: list[str]) -> None:
    artifacts_dir = plan.placement.planner_artifacts_dir
    if not artifacts_dir:
        return
    try:
        from sase.plan_approval_actions import (
            PlanApprovalActionContext,
            record_plan_approval_metadata,
        )

        context = PlanApprovalActionContext(
            id=plan.gate.notification_id if plan.gate is not None else plan.name,
            host_files=(str(plan.source_path),),
            host_action_data={"artifacts_dir": artifacts_dir},
        )
        record_plan_approval_metadata(
            context, plan.kind, plan_committed=plan.kind in ("tale", "commit")
        )
    except Exception as exc:
        warnings.append(f"planner metadata could not be recorded: {exc}")


__all__ = ["DirectApprovalOutcome", "execute_direct_approval"]
