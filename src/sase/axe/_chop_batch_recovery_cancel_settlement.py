"""Dead-executor settlement for cancelled batches with in-flight evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import chop_batch_store
from ._chop_batch_recovery_observations import (
    collect_spawn_observations_with_completeness,
)
from ._chop_batch_recovery_shared import (
    ChopBatchRecoveryResult,
    batch_clan,
    deliver_pending_batch_notices,
    emit_batch_notice,
    summarize_manifest,
)


def recover_cancelled_batch(
    routine: str,
    job: str,
    batch_id: str,
    manifest: Mapping[str, Any],
) -> ChopBatchRecoveryResult:
    """Reconcile a cancelled batch that still owns dispatching members.

    A live owner still wins. For a dead owner, durable linkage settles a real
    launch exactly once via the crossing-launch acknowledgement path, complete
    absence settles the cancelled intent without launching, and ambiguity
    stays visibly held. Cancellation is never reopened and no member is
    retried. Retirement happens only after evidence, history and notices
    settle.
    """
    if not chop_batch_store.acquire_chop_batch_ownership(
        routine, job, batch_id, owner="cancelled-settlement"
    ):
        return ChopBatchRecoveryResult(
            routine=routine,
            job=job,
            batch_id=batch_id,
            kind="blocked",
            reason=f"batch {batch_id!r} already has a live owner",
        )
    try:
        observations, complete, incomplete_reason = (
            collect_spawn_observations_with_completeness(routine, job, manifest)
        )
        if not complete:
            return ChopBatchRecoveryResult(
                routine=routine,
                job=job,
                batch_id=batch_id,
                kind="blocked",
                reason=(
                    "cancelled batch evidence is incomplete; holding without "
                    f"settlement: {incomplete_reason or 'unreadable evidence'}"
                ),
            )
        by_name = {
            str(item.get("agent_name") or ""): str(item.get("observation") or "")
            for item in observations
        }
        members = manifest.get("members")
        dispatching_indexes: list[int] = []
        if isinstance(members, list):
            for position, member in enumerate(members):
                if (
                    isinstance(member, Mapping)
                    and str(member.get("status") or "") == "dispatching"
                ):
                    dispatching_indexes.append(position)
        if not dispatching_indexes:
            return ChopBatchRecoveryResult(
                routine=routine,
                job=job,
                batch_id=batch_id,
                kind="cancelled",
                reason="batch was explicitly cancelled",
            )
        # Typed linkage fold first so typed receipts settle before outer ack.
        if isinstance(manifest.get("typed_bundle"), Mapping):
            try:
                from ._chop_typed_admission_batch import (
                    replay_linkage_proven_dispatches,
                )
                from sase.agent.launch_admission_request_data import (
                    typed_plan_from_request,
                )
                from sase.agent.direct_typed_launch import typed_launch_bundle_dir
                from sase.agent.launch_request_response import read_launch_request

                bundle_ref = manifest["typed_bundle"]
                bundle_id = str(bundle_ref.get("bundle_id") or "")
                if bundle_id:
                    bundle_dir = typed_launch_bundle_dir(bundle_id)
                    payload = read_launch_request(bundle_dir)
                    typed_plan = typed_plan_from_request(payload)
                    replay_linkage_proven_dispatches(
                        routine,
                        job,
                        batch_id,
                        bundle_dir=bundle_dir,
                        payload=payload,
                        typed_plan=typed_plan,
                    )
            except Exception:
                pass
        settled_launched: list[int] = []
        held: list[dict[str, Any]] = []
        for position in dispatching_indexes:
            member = members[position] if isinstance(members, list) else None
            if not isinstance(member, Mapping):
                continue
            name = str(member.get("agent_name") or "")
            observation = by_name.get(name)
            if observation == "matched_spawn":
                try:
                    chop_batch_store.apply_chop_batch_event(
                        routine,
                        job,
                        batch_id,
                        "acknowledge_launch",
                        member_index=position,
                    )
                    settled_launched.append(position)
                except Exception as exc:
                    held.append(
                        {
                            "agent_name": name,
                            "status": "dispatching",
                            "reason": f"cannot settle proven spawn: {exc}",
                        }
                    )
            elif observation is None or observation == "reservation_only":
                try:
                    chop_batch_store.apply_chop_batch_event(
                        routine,
                        job,
                        batch_id,
                        "settle_cancelled_dispatch",
                        member_index=position,
                        reason=(
                            "dead executor; complete evidence shows no spawn "
                            "for a cancelled batch"
                        ),
                    )
                except Exception as exc:
                    # Core can refuse this settlement; hold visibly rather
                    # than retiring unsettled evidence.
                    held.append(
                        {
                            "agent_name": name,
                            "status": "dispatching",
                            "reason": f"cannot settle cancelled dispatch: {exc}",
                        }
                    )
            else:
                reason = (
                    "foreign owner holds the name; leaving cancelled dispatch unsettled"
                    if observation == "foreign_conflict"
                    else (
                        "live owner holds the name; leaving cancelled dispatch "
                        "unsettled"
                        if observation == "live_owner"
                        else f"ambiguous spawn evidence ({observation or 'held'}); holding"
                    )
                )
                held.append(
                    {"agent_name": name, "status": "dispatching", "reason": reason}
                )
        if held:
            try:
                refreshed = chop_batch_store.load_chop_batch(routine, job, batch_id)
                summary = summarize_manifest(refreshed)
                emit_batch_notice(
                    routine=routine,
                    job=job,
                    batch_id=batch_id,
                    event="hold",
                    launched=summary["launched"],
                    remaining=summary["remaining"],
                    clan=batch_clan(refreshed),
                    reason="; ".join(
                        str(item.get("reason") or item.get("agent_name") or "held")
                        for item in held
                    ),
                    hold_key="cancelled-settlement-ambiguity",
                )
            except Exception:
                pass
            return ChopBatchRecoveryResult(
                routine=routine,
                job=job,
                batch_id=batch_id,
                kind="blocked",
                blocked=tuple(held),
                reason="cancelled batch holds ambiguous dispatch evidence",
            )
        # All in-flight evidence settled: merge proven launches into run history
        # exactly once, deliver pending notices, then allow retirement.
        try:
            from ._chop_batch_recovery_resume_ordinary import (
                backfill_launched_history_descriptors,
                merge_resumed_launches_into_run,
            )

            merge_resumed_launches_into_run(
                routine,
                job,
                batch_id,
                backfill_launched_history_descriptors(
                    routine, job, batch_id, settled_launched
                ),
            )
        except Exception:
            pass
        try:
            deliver_pending_batch_notices(routine, job, batch_id)
        except Exception:
            pass
        return ChopBatchRecoveryResult(
            routine=routine,
            job=job,
            batch_id=batch_id,
            kind="cancelled",
            already_launched=tuple(settled_launched),
            reason="batch was explicitly cancelled",
        )
    finally:
        chop_batch_store.release_and_retire_chop_batch(routine, job, batch_id)
