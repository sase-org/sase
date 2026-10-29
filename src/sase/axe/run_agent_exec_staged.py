"""Adopt staged handoffs after the ordinary finalizer controller settles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from sase.agent.staged_handoff import (
    StagedHandoffError,
    read_adoption_receipt,
    read_staged_handoff,
    read_staged_handoff_response,
    receipt_authorizes,
    write_adoption_receipt,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import AgentExecContext, LoopState


@dataclass(frozen=True)
class StagedInlineContinuation:
    """Runner-only state needed to continue a plan inline after adoption."""

    ctx: AgentExecContext
    state: LoopState


@dataclass(frozen=True)
class _StagedHandoffDispatch:
    """Result of examining and, when safe, adopting one staged handoff."""

    adopted: bool
    outcome: str | None = None
    reason: str | None = None
    already_adopted: bool = False


StagedAdopter = Callable[
    [Mapping[str, Any], Mapping[str, Any], StagedInlineContinuation, str],
    str | None,
]


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StagedHandoffError(f"malformed {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise StagedHandoffError(f"malformed {label}: not a JSON object")
    return payload


def _read_run_metadata(artifacts_dir: str) -> dict[str, Any]:
    return _read_json_object(
        Path(artifacts_dir) / "agent_meta.json", label="agent metadata"
    )


def _timestamp(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.timestamp()


def _finalizer_settlement_refusal(
    staged_record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
) -> str | None:
    """Return why this staged record lacks same-turn finalizer proof."""
    root = Path(artifacts_dir)
    result = _read_json_object(root / "finalizer_result.json", label="finalizer result")
    result_status = result.get("status")
    if result_status not in {"success", "deferred"}:
        return "finalizer controller did not settle successfully"

    summary = run_metadata.get("finalizer_status")
    if not isinstance(summary, Mapping):
        return "finalizer settlement summary is missing"
    if summary.get("phase") != "settled" or summary.get("status") != result_status:
        return "finalizer settlement summary does not match the result"
    settlement_id = summary.get("run_id")
    plan_digest = summary.get("plan_digest")
    started_at = summary.get("started_at")
    if not isinstance(settlement_id, str) or not settlement_id:
        return "finalizer settlement has no run identity"
    if not isinstance(plan_digest, str) or not plan_digest:
        return "finalizer settlement has no plan identity"
    if isinstance(started_at, bool) or not isinstance(started_at, int | float):
        return "finalizer settlement has no start time"
    staged_at = _timestamp(staged_record.get("created_at"))
    if staged_at is None or float(started_at) < staged_at:
        return "finalizer settlement does not follow this staged handoff"

    from sase.finalizers.plan import authenticate_resolved_finalizer_plan

    plan = authenticate_resolved_finalizer_plan(str(root))
    if plan.plan_digest != plan_digest:
        return "finalizer settlement does not match the sealed plan"
    context: Mapping[str, Any] | None = None
    if plan.entries:
        final_context_payload = _read_json_object(
            root / "final_context.json", label="finalizer context"
        )
        raw_context = final_context_payload.get("context")
        if not isinstance(raw_context, Mapping):
            return "finalizer context is missing its persisted context"
        context = raw_context
        from sase.ace.tui.models._timestamps import normalize_to_14_digit

        expected_run_id = normalize_to_14_digit(root.name) or root.name
        if context.get("run_id") != expected_run_id:
            return "finalizer context belongs to a different turn"
        if context.get("plan_digest") != plan_digest:
            return "finalizer context does not match the settled plan"
        persisted_name = run_metadata.get("name")
        if (
            isinstance(persisted_name, str)
            and context.get("agent_id") != persisted_name
        ):
            return "finalizer context does not match the persisted agent identity"
    elif result_status != "success":
        return "an empty finalizer plan must settle with success"

    entries_by_id = {entry.instance_id: entry for entry in plan.entries}
    raw_results = result.get("instances")
    if not isinstance(raw_results, list):
        return "finalizer result has no instance results"
    results_by_id = {
        item.get("instance_id"): item
        for item in raw_results
        if isinstance(item, Mapping) and isinstance(item.get("instance_id"), str)
    }
    if set(results_by_id) != set(entries_by_id):
        if entries_by_id or results_by_id:
            return "finalizer result does not cover the selected instances"

    deferred_commit_ids: set[str] = set()
    for instance_id, entry in entries_by_id.items():
        status = results_by_id[instance_id].get("status")
        if status == "success":
            continue
        if status == "deferred" and entry.provider_ref == "builtin@commit":
            deferred_commit_ids.add(instance_id)
            continue
        return f"finalizer instance {instance_id!r} did not settle successfully"
    if bool(deferred_commit_ids) != (result_status == "deferred"):
        return "finalizer result status does not match its deferred instances"

    from sase.finalizers.declaration import (
        FINAL_SUBMISSION_FILENAME,
        final_submission_is_current,
        load_latest_finalizer_context,
        load_latest_finalizer_submission,
    )
    from sase.finalizers.declaration_store import repository_obligation_id
    from sase.llm_provider.commit_finalizer_state import collect_dirty_state

    project_dir = run_metadata.get("workspace_dir")
    if not isinstance(project_dir, str) or not project_dir:
        return "persisted workspace identity is missing"
    dirty_state = collect_dirty_state(project_dir, artifact_root=root)
    dirty_ids = {repository_obligation_id(repo) for repo in dirty_state.repos}
    if not dirty_ids and not deferred_commit_ids:
        return None

    if not (root / FINAL_SUBMISSION_FILENAME).is_file():
        return "remaining repository work has no accepted final declaration"
    try:
        submission = load_latest_finalizer_submission(root)
    except Exception as exc:  # noqa: BLE001 - malformed evidence must hold adoption.
        return f"accepted final declaration is unreadable: {exc}"
    accepted_deferrals = submission.get("accepted_deferrals")
    if not isinstance(accepted_deferrals, list):
        accepted_deferrals = []
    commit_ids = {
        instance_id
        for instance_id, entry in entries_by_id.items()
        if entry.provider_ref == "builtin@commit"
    }
    deferred_repos = {
        item.get("repo_id")
        for item in accepted_deferrals
        if isinstance(item, Mapping)
        and item.get("instance_id") in commit_ids
        and isinstance(item.get("repo_id"), str)
    }
    if not deferred_commit_ids.issubset(
        {
            item.get("instance_id")
            for item in accepted_deferrals
            if isinstance(item, Mapping) and item.get("instance_id") in commit_ids
        }
    ):
        return "deferred commit finalizer has no accepted typed deferral"

    if dirty_ids:
        if not commit_ids:
            return "remaining repository work is not covered by a commit finalizer"
        current_final_context = load_latest_finalizer_context(root)
        context_ids = {
            obligation.obligation_id
            for obligation in current_final_context.obligations
            if obligation.kind == "repository"
        }
        if not dirty_ids.issubset(context_ids):
            return "finalizer re-observation found repository work outside its context"
        if not final_submission_is_current(artifacts_dir=str(root)):
            return "remaining repository work is not covered by a current declaration"
        if not dirty_ids.issubset(deferred_repos):
            return "remaining repository work is neither committed nor an accepted deferral"

    return None


def _adopt_plan(
    staged_record: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
    continuation: StagedInlineContinuation,
    response: str,
) -> str | None:
    payload = staged_record.get("payload")
    if not isinstance(payload, Mapping):
        raise StagedHandoffError("staged plan payload is malformed")
    plan_file = payload.get("plan_file")
    if not isinstance(plan_file, str) or not plan_file:
        raise StagedHandoffError("staged plan payload has no plan_file")

    ctx = continuation.ctx
    state = continuation.state
    persisted_name = run_metadata.get("name")
    if isinstance(persisted_name, str) and persisted_name != ctx.agent_name:
        raise StagedHandoffError(
            "persisted planner identity differs from the active runner identity"
        )
    persisted_ctx = replace(
        ctx,
        agent_name=persisted_name
        if isinstance(persisted_name, str)
        else ctx.agent_name,
        agent_model=run_metadata.get("model", ctx.agent_model),
        agent_llm_provider=run_metadata.get("llm_provider", ctx.agent_llm_provider),
        agent_vcs_provider=run_metadata.get("vcs_provider", ctx.agent_vcs_provider),
        agent_meta=dict(run_metadata),
    )
    from sase.axe.run_agent_exec_plan import handle_staged_plan_marker

    return handle_staged_plan_marker(
        {**dict(payload), "plan_file": plan_file},
        persisted_ctx,
        state,
        planner_response=response,
    )


STAGED_HANDOFF_ADOPTERS: dict[str, StagedAdopter] = {"plan": _adopt_plan}


def _write_held_receipt(
    staged_id: str,
    reason: str,
    *,
    artifacts_dir: str,
) -> None:
    write_adoption_receipt(
        {
            "staged_id": staged_id,
            "adopted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "outcome": "handoff_not_adopted",
            "reason": reason,
        },
        artifacts_dir=artifacts_dir,
    )


def dispatch_completed_staged_handoff(
    artifacts_dir: str,
    continuation: StagedInlineContinuation,
) -> _StagedHandoffDispatch | None:
    """Adopt a staged handoff only after the finalizer fixed point succeeds."""
    staged_record = read_staged_handoff(artifacts_dir)
    if staged_record is None:
        return None
    staged_id = str(staged_record["staged_id"])

    receipt = read_adoption_receipt(artifacts_dir)
    if receipt is not None and receipt_authorizes(receipt, staged_id):
        receipt_refs = receipt.get("refs")
        receipt_refs = receipt_refs if isinstance(receipt_refs, Mapping) else {}
        outcome = receipt_refs.get("loop_outcome")
        if outcome is not None and not isinstance(outcome, str):
            raise StagedHandoffError(
                "staged adoption receipt has an invalid loop outcome"
            )
        if "loop_outcome" not in receipt_refs:
            outcome = "completed"
        return _StagedHandoffDispatch(
            adopted=True,
            outcome=outcome,
            already_adopted=True,
        )

    run_metadata = _read_run_metadata(artifacts_dir)
    refusal = _finalizer_settlement_refusal(
        staged_record,
        artifacts_dir=artifacts_dir,
        run_metadata=run_metadata,
    )
    if refusal is not None:
        _write_held_receipt(staged_id, refusal, artifacts_dir=artifacts_dir)
        return _StagedHandoffDispatch(adopted=False, reason=refusal)

    response = read_staged_handoff_response(staged_id, artifacts_dir=artifacts_dir)
    if response is None:
        reason = "ordinary provider response was not persisted for this staged handoff"
        _write_held_receipt(staged_id, reason, artifacts_dir=artifacts_dir)
        return _StagedHandoffDispatch(adopted=False, reason=reason)

    adopter = STAGED_HANDOFF_ADOPTERS.get(str(staged_record.get("kind")))
    if adopter is None:
        reason = f"unsupported staged handoff kind {staged_record.get('kind')!r}"
        _write_held_receipt(staged_id, reason, artifacts_dir=artifacts_dir)
        return _StagedHandoffDispatch(adopted=False, reason=reason)

    original_artifacts_dir = artifacts_dir
    original_state_artifacts_dir = continuation.state.current_artifacts_dir
    try:
        outcome = adopter(staged_record, run_metadata, continuation, response)
        if outcome == "plan_rejected":
            reason = "staged plan could not be adopted by the plan approval flow"
            _write_held_receipt(staged_id, reason, artifacts_dir=original_artifacts_dir)
            return _StagedHandoffDispatch(adopted=False, reason=reason)
    except Exception as exc:
        _write_held_receipt(
            staged_id,
            f"staged plan adoption failed: {type(exc).__name__}: {exc}",
            artifacts_dir=original_artifacts_dir,
        )
        raise

    adoption_refs: dict[str, Any] = {"loop_outcome": outcome}
    if continuation.state.plan_gate_artifacts_dir:
        adoption_refs["plan_gate_artifacts_dir"] = (
            continuation.state.plan_gate_artifacts_dir
        )
    if continuation.state.current_artifacts_dir != original_state_artifacts_dir:
        adoption_refs["successor_artifacts_dir"] = (
            continuation.state.current_artifacts_dir
        )
    write_adoption_receipt(
        {
            "staged_id": staged_id,
            "adopted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "outcome": "adopted",
            "refs": adoption_refs,
        },
        artifacts_dir=original_artifacts_dir,
    )
    from sase.axe.run_agent_helpers import update_meta_field

    update_meta_field(original_artifacts_dir, "handoff_protocol", "staged")
    return _StagedHandoffDispatch(adopted=True, outcome=outcome)


__all__ = [
    "STAGED_HANDOFF_ADOPTERS",
    "StagedInlineContinuation",
    "dispatch_completed_staged_handoff",
]
