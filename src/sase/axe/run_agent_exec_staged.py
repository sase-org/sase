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


@dataclass(frozen=True)
class StagedAdoptionOutcome:
    """Narrow adopter result carrying an explicit custodian identity.

    ``outcome`` preserves the legacy ``str | None`` loop-outcome semantics
    (``None`` continues inline). ``custodian`` is the actual successor
    artifacts identity that now owns carried work, when the adopter knows
    it. When ``None``, dispatch derives the custodian from continuation
    state (successor/gate dirs), never from command text.
    """

    outcome: str | None = None
    custodian: str | None = None


StagedAdopter = Callable[
    [Mapping[str, Any], Mapping[str, Any], StagedInlineContinuation, str],
    str | None | StagedAdoptionOutcome,
]

#: Agent-meta key holding carried-repository custody records. Each record is
#: ``{"repo_id": str, "digest": str, "staged_id": str, "origin_run": str,
#: "carried_to": str | None}``. ``carried_to`` is ``None`` while the origin
#: retains custody and holds the actual successor identity after adoption.
CARRIED_CUSTODY_META_KEY = "carried_repositories"


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


def _staged_identity_matches(
    staged_record: Mapping[str, Any],
    handoff: Any,
) -> bool:
    """Return whether the persisted handoff descriptor matches the stage."""
    staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        return False
    staged_ref = getattr(handoff, "staged_ref", None)
    if staged_ref != staged_id:
        return False
    record_kind = staged_record.get("kind")
    if isinstance(record_kind, str) and record_kind:
        handoff_kind = str(getattr(handoff, "kind", "") or "")
        if handoff_kind and handoff_kind != record_kind:
            return False
    record_workspace = staged_record.get("successor_workspace")
    if isinstance(record_workspace, str) and record_workspace:
        handoff_workspace = str(getattr(handoff, "successor_workspace", "") or "")
        if handoff_workspace and handoff_workspace != record_workspace:
            return False
    record_carry = staged_record.get("carry_allowed")
    if isinstance(record_carry, bool):
        handoff_carry = getattr(handoff, "carry_allowed", None)
        if isinstance(handoff_carry, bool) and handoff_carry != record_carry:
            return False
    return True


def _proven_ids_for_settlement(
    result_payload: Mapping[str, Any],
    current_context: Any,
    staged_id: str,
) -> frozenset[str]:
    """Return dirty ids with current carry/prepared proof for *staged_id*."""
    from sase.finalizers.commit_carry import proven_coverage_ids_from_result_payload

    digest_by_id = {
        obligation.obligation_id: obligation.digest or ""
        for obligation in getattr(current_context, "obligations", ())
        if getattr(obligation, "kind", "") == "repository"
    }
    try:
        return proven_coverage_ids_from_result_payload(
            result_payload,
            digest_by_id=digest_by_id,
            staged_ref=staged_id,
        )
    except Exception:
        return frozenset()


def _origin_run_id(run_metadata: Mapping[str, Any], artifacts_dir: str) -> str:
    summary = run_metadata.get("finalizer_status")
    if isinstance(summary, Mapping):
        run_id = summary.get("run_id")
        if isinstance(run_id, str) and run_id:
            return run_id
    name = run_metadata.get("name")
    if isinstance(name, str) and name:
        return name
    return Path(artifacts_dir).name


def _collect_carried_custody_records(
    staged_record: Mapping[str, Any],
    *,
    result_payload: Mapping[str, Any],
    current_context: Any,
    origin_run: str,
) -> list[dict[str, Any]]:
    """Build custody records for every proven carried/prepared repository."""
    from sase.finalizers.commit_carry import proven_coverage_ids_from_result_payload

    staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        return []
    digest_by_id = {
        obligation.obligation_id: obligation.digest or ""
        for obligation in getattr(current_context, "obligations", ())
        if getattr(obligation, "kind", "") == "repository"
    }
    try:
        proven = proven_coverage_ids_from_result_payload(
            result_payload,
            digest_by_id=digest_by_id,
            staged_ref=staged_id,
        )
    except Exception:
        return []
    return [
        {
            "repo_id": repo_id,
            "digest": digest_by_id.get(repo_id, ""),
            "staged_id": staged_id,
            "origin_run": origin_run,
            "carried_to": None,
        }
        for repo_id in sorted(proven)
    ]


def _persist_origin_custody(
    staged_record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Persist origin custody records for proven carry/prepared coverage."""
    from sase.axe.run_agent_helpers_artifacts import update_meta_fields

    root = Path(artifacts_dir)
    try:
        result_payload = _read_json_object(
            root / "finalizer_result.json", label="finalizer result"
        )
    except StagedHandoffError:
        return []
    from sase.finalizers.declaration import load_latest_finalizer_context

    try:
        current_context = load_latest_finalizer_context(root)
    except Exception:
        return []
    records = _collect_carried_custody_records(
        staged_record,
        result_payload=result_payload,
        current_context=current_context,
        origin_run=_origin_run_id(run_metadata, artifacts_dir),
    )
    if not records:
        return []
    try:
        meta = _read_json_object(root / "agent_meta.json", label="agent metadata")
    except StagedHandoffError:
        return []
    existing = meta.get(CARRIED_CUSTODY_META_KEY)
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    if isinstance(existing, list):
        for item in existing:
            if not isinstance(item, Mapping):
                continue
            repo_id = item.get("repo_id")
            staged_id = item.get("staged_id")
            if not isinstance(repo_id, str) or not isinstance(staged_id, str):
                continue
            merged[(staged_id, repo_id)] = dict(item)
    for record in records:
        key = (str(record["staged_id"]), str(record["repo_id"]))
        prior = merged.get(key)
        if isinstance(prior, dict) and isinstance(prior.get("carried_to"), str):
            # A completed transfer is durable; never clear it on re-persist.
            continue
        merged[key] = record
    update_meta_fields(
        artifacts_dir,
        {
            CARRIED_CUSTODY_META_KEY: sorted(
                merged.values(),
                key=lambda r: (str(r.get("staged_id")), str(r.get("repo_id"))),
            )
        },
    )
    return records


def _mark_custody_transferred(
    staged_record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    carried_to: str,
) -> None:
    """Record the actual successor identity on this stage's custody records."""
    from sase.axe.run_agent_helpers_artifacts import update_meta_fields

    if not carried_to.strip():
        return
    staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        return
    root = Path(artifacts_dir)
    try:
        meta = _read_json_object(root / "agent_meta.json", label="agent metadata")
    except StagedHandoffError:
        return
    existing = meta.get(CARRIED_CUSTODY_META_KEY)
    if not isinstance(existing, list) or not existing:
        return
    updated: list[dict[str, Any]] = []
    changed = False
    for item in existing:
        if (
            isinstance(item, Mapping)
            and item.get("staged_id") == staged_id
            and isinstance(item.get("repo_id"), str)
        ):
            record = dict(item)
            if record.get("carried_to") != carried_to:
                record["carried_to"] = carried_to
                changed = True
            updated.append(record)
        elif isinstance(item, Mapping):
            updated.append(dict(item))
    if changed:
        update_meta_fields(artifacts_dir, {CARRIED_CUSTODY_META_KEY: updated})


def _normalize_adopter_result(
    raw: str | None | StagedAdoptionOutcome,
) -> tuple[str | None, str | None]:
    """Split a legacy or narrow adopter return into outcome and custodian."""
    if isinstance(raw, StagedAdoptionOutcome):
        return raw.outcome, raw.custodian
    return raw, None


def _resolve_adoption_custodian(
    *,
    explicit: str | None,
    continuation: StagedInlineContinuation,
    original_artifacts_dir: str,
) -> str:
    """Return the actual custodian identity without guessing from commands."""
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    state = continuation.state
    successor = getattr(state, "current_artifacts_dir", "") or ""
    if isinstance(successor, str) and successor.strip():
        original = Path(original_artifacts_dir).resolve(strict=False)
        current = Path(successor).resolve(strict=False)
        if str(current) != str(original):
            return str(successor)
    gate_dir = getattr(state, "plan_gate_artifacts_dir", None)
    if isinstance(gate_dir, str) and gate_dir.strip():
        return gate_dir.strip()
    if isinstance(successor, str) and successor.strip():
        return successor.strip()
    return str(original_artifacts_dir)


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

    commit_ids = {
        instance_id
        for instance_id, entry in entries_by_id.items()
        if entry.provider_ref == "builtin@commit"
    }
    has_submission = (root / FINAL_SUBMISSION_FILENAME).is_file()
    accepted_deferrals: list[Any] = []
    if has_submission:
        try:
            submission = load_latest_finalizer_submission(root)
        except Exception as exc:  # noqa: BLE001 - malformed evidence must hold adoption.
            return f"accepted final declaration is unreadable: {exc}"
        raw_deferrals = submission.get("accepted_deferrals")
        if isinstance(raw_deferrals, list):
            accepted_deferrals = raw_deferrals
    deferred_repos = {
        item.get("repo_id")
        for item in accepted_deferrals
        if isinstance(item, Mapping)
        and item.get("instance_id") in commit_ids
        and isinstance(item.get("repo_id"), str)
    }
    if has_submission and not deferred_commit_ids.issubset(
        {
            item.get("instance_id")
            for item in accepted_deferrals
            if isinstance(item, Mapping) and item.get("instance_id") in commit_ids
        }
    ):
        return "deferred commit finalizer has no accepted typed deferral"

    if dirty_ids:
        if not has_submission:
            # No accepted declaration: only a prepared starter with
            # authenticated prepared coverage may omit submission. Preserve
            # the legacy refusal when prepared proof cannot apply.
            try:
                no_submission_context = load_latest_finalizer_context(root)
            except Exception:
                return "remaining repository work has no accepted final declaration"
            no_sub_handoff = getattr(no_submission_context, "handoff", None)
            if no_sub_handoff is None:
                return "remaining repository work has no accepted final declaration"
            staged_id_ns = staged_record.get("staged_id")
            staged_ref_ns = staged_id_ns if isinstance(staged_id_ns, str) else ""
            if not _staged_identity_matches(staged_record, no_sub_handoff):
                return "remaining repository work has no accepted final declaration"
            if getattr(no_sub_handoff, "prepared_intent_ref", None) is None:
                return "remaining repository work has no accepted final declaration"
            if not staged_ref_ns:
                return "remaining repository work has no accepted final declaration"
            proven_ns = _proven_ids_for_settlement(
                result, no_submission_context, staged_ref_ns
            )
            if not dirty_ids.issubset(proven_ns):
                return "prepared starter coverage does not cover the remaining work"
            return None
        if not commit_ids:
            return "remaining repository work is not covered by a commit finalizer"
        try:
            current_final_context = load_latest_finalizer_context(root)
        except Exception as exc:  # noqa: BLE001 - unreadable context must hold adoption.
            return f"finalizer context is unreadable: {exc}"
        context_ids = {
            obligation.obligation_id
            for obligation in current_final_context.obligations
            if obligation.kind == "repository"
        }
        if not dirty_ids.issubset(context_ids):
            return "finalizer re-observation found repository work outside its context"
        staged_id = staged_record.get("staged_id")
        staged_ref = staged_id if isinstance(staged_id, str) else ""
        handoff = getattr(current_final_context, "handoff", None)
        descriptor_matches = (
            _staged_identity_matches(staged_record, handoff)
            if handoff is not None
            else False
        )
        proven: frozenset[str] = frozenset()
        if descriptor_matches and staged_ref:
            proven = _proven_ids_for_settlement(
                result, current_final_context, staged_ref
            )
        if not final_submission_is_current(artifacts_dir=str(root)):
            return "remaining repository work is not covered by a current declaration"
        allowed = deferred_repos | (proven if descriptor_matches else frozenset())
        if not dirty_ids.issubset(allowed):
            if descriptor_matches and proven:
                return (
                    "remaining repository work is neither committed, carried, "
                    "prepared, nor an accepted deferral"
                )
            return "remaining repository work is neither committed nor an accepted deferral"
        return None

    if not has_submission and not deferred_commit_ids:
        return None
    if not has_submission:
        return "remaining repository work has no accepted final declaration"
    if not final_submission_is_current(artifacts_dir=str(root)):
        return "remaining repository work is not covered by a current declaration"
    return None


def _adopt_plan(
    staged_record: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
    continuation: StagedInlineContinuation,
    response: str,
) -> str | None | StagedAdoptionOutcome:
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

    # Settlement is proven: persist origin custody before any adopter runs so
    # a failed adoption leaves origin evidence intact.
    _persist_origin_custody(
        staged_record, artifacts_dir=artifacts_dir, run_metadata=run_metadata
    )

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
        raw_outcome = adopter(staged_record, run_metadata, continuation, response)
        outcome, explicit_custodian = _normalize_adopter_result(raw_outcome)
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

    custodian = _resolve_adoption_custodian(
        explicit=explicit_custodian,
        continuation=continuation,
        original_artifacts_dir=original_artifacts_dir,
    )
    _mark_custody_transferred(
        staged_record, artifacts_dir=original_artifacts_dir, carried_to=custodian
    )

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
    "CARRIED_CUSTODY_META_KEY",
    "STAGED_HANDOFF_ADOPTERS",
    "StagedAdoptionOutcome",
    "StagedInlineContinuation",
    "dispatch_completed_staged_handoff",
]
