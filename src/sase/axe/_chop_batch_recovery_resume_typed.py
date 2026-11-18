"""Resume typed chop batches after interruption."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from . import chop_batch_store
from ._chop_batch_recovery_shared import (
    ChopBatchRecoveryResult,
    batch_clan,
    deliver_pending_batch_notices,
    emit_batch_notice,
    pending_interruption_episode,
    prepare_batch_notice,
    summarize_manifest,
)
from .chop_batch_store import ChopBatchError


def recover_typed_batch(
    routine: str,
    job: str,
    batch_id: str,
    manifest: Mapping[str, Any],
    *,
    launch_agents_from_cwd_fn: Callable[..., Any] | None,
    launch_agent_from_cwd_fn: Callable[..., Any] | None,
    pause_requested_fn: Callable[[], bool] | None,
) -> ChopBatchRecoveryResult:
    from .chop_typed_admission import resume_typed_chop_batch

    if not chop_batch_store.acquire_chop_batch_ownership(
        routine, job, batch_id, owner="typed-recovery"
    ):
        return ChopBatchRecoveryResult(
            routine=routine,
            job=job,
            batch_id=batch_id,
            kind="blocked",
            reason=f"batch {batch_id!r} already has a live owner",
        )
    ownership_delegated = False
    try:
        clan = batch_clan(manifest)
        initial = summarize_manifest(manifest)
        deliver_pending_batch_notices(routine, job, batch_id)
        episode_id = pending_interruption_episode(routine, job, batch_id)
        recovery_evidence = (
            initial["launched"] > 0
            or str(manifest.get("status") or "") == "paused"
            or any(
                isinstance(member, Mapping)
                and str(member.get("status") or "") == "dispatching"
                for member in manifest.get("members", [])
            )
        )
        if episode_id is None and recovery_evidence:
            episode_id = emit_batch_notice(
                routine=routine,
                job=job,
                batch_id=batch_id,
                event="interrupted",
                launched=initial["launched"],
                remaining=initial["remaining"],
                clan=clan,
            )
        if episode_id is not None:
            prepare_batch_notice(
                routine=routine,
                job=job,
                batch_id=batch_id,
                event="resumed",
                launched=initial["launched"],
                remaining=initial["remaining"],
                clan=clan,
                episode_id=episode_id,
            )
        ownership_delegated = True
        try:
            resumed = resume_typed_chop_batch(
                routine,
                job,
                batch_id,
                launch_agents_from_cwd_fn=launch_agents_from_cwd_fn,
                launch_recorded_fn=None,
                pause_requested_fn=pause_requested_fn,
                ownership_acquired=True,
            )
        finally:
            # Take release duty back before the history merge and finish
            # notices: resume no longer retires a delegated batch, so the
            # outbox stays authoritative until the finish notice is delivered.
            ownership_delegated = False
        from ._chop_batch_recovery_resume_ordinary import (
            backfill_launched_history_descriptors,
            merge_resumed_launches_into_run,
        )

        try:
            typed_members = chop_batch_store.load_chop_batch(
                routine, job, batch_id
            ).get("members")
        except ChopBatchError:
            typed_members = []
        launched_indexes = [
            position
            for position, item in enumerate(typed_members or [])
            if isinstance(item, Mapping) and str(item.get("status") or "") == "launched"
        ]
        # `resumed.launches` covers this pass; the backfill restores members
        # acknowledged before the interruption from their durable linkage, so
        # the original run's history lists every member exactly once. The
        # merge dedupes on (index, name, pid), making repeats idempotent.
        merge_resumed_launches_into_run(
            routine,
            job,
            batch_id,
            [
                *resumed.launches,
                *backfill_launched_history_descriptors(
                    routine, job, batch_id, launched_indexes
                ),
            ],
        )
        try:
            refreshed = chop_batch_store.load_chop_batch(routine, job, batch_id)
            summary = summarize_manifest(refreshed)
        except ChopBatchError:
            summary = {"launched": len(resumed.launches), "remaining": 0}
        if episode_id is not None:
            emit_batch_notice(
                routine=routine,
                job=job,
                batch_id=batch_id,
                event="resumed",
                launched=int(summary["launched"]),
                remaining=int(summary["remaining"]),
                clan=clan,
                episode_id=episode_id,
            )
        return ChopBatchRecoveryResult(
            routine=routine,
            job=job,
            batch_id=batch_id,
            kind="blocked" if resumed.waiting else "typed",
            launched=tuple(resumed.launches),
            paused=bool(resumed.paused),
            reason=(
                "batch already has a live owner or typed coordinator; recovery is waiting"
                if resumed.waiting
                else None
            ),
        )
    except Exception as exc:
        return ChopBatchRecoveryResult(
            routine=routine,
            job=job,
            batch_id=batch_id,
            kind="blocked",
            reason=str(exc),
        )
    finally:
        if not ownership_delegated:
            chop_batch_store.release_and_retire_chop_batch(routine, job, batch_id)
