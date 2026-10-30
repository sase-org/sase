"""Same-turn finalizer settlement proof for staged-handoff adoption."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.axe._run_agent_exec_staged_shared import (
    proven_ids_for_settlement,
    read_json_object,
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


def finalizer_settlement_refusal(
    staged_record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
) -> str | None:
    """Return why this staged record lacks same-turn finalizer proof."""
    root = Path(artifacts_dir)
    result = read_json_object(root / "finalizer_result.json", label="finalizer result")
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
        final_context_payload = read_json_object(
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
            proven_ns = proven_ids_for_settlement(
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
            proven = proven_ids_for_settlement(
                result, current_final_context, staged_ref
            )
        allowed = deferred_repos | (proven if descriptor_matches else frozenset())
        if dirty_ids.issubset(allowed):
            return None
        if not final_submission_is_current(artifacts_dir=str(root)):
            return "remaining repository work is not covered by a current declaration"
        if descriptor_matches and proven:
            return (
                "remaining repository work is neither committed, carried, "
                "prepared, nor an accepted deferral"
            )
        return "remaining repository work is neither committed nor an accepted deferral"

    if not has_submission and not deferred_commit_ids:
        return None
    if not has_submission:
        return "remaining repository work has no accepted final declaration"
    if not final_submission_is_current(artifacts_dir=str(root)):
        return "remaining repository work is not covered by a current declaration"
    return None


__all__ = ["finalizer_settlement_refusal"]
