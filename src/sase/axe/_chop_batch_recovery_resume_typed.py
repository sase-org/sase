"""Resume typed chop batches after interruption."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from . import chop_batch_store
from ._chop_batch_recovery_shared import (
    ChopBatchRecoveryResult,
    batch_clan,
    emit_batch_notice,
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

    clan = batch_clan(manifest)
    try:
        resumed = resume_typed_chop_batch(
            routine,
            job,
            batch_id,
            launch_agents_from_cwd_fn=launch_agents_from_cwd_fn,
            launch_recorded_fn=None,
            pause_requested_fn=pause_requested_fn,
        )
    except Exception as exc:
        return ChopBatchRecoveryResult(
            routine=routine,
            job=job,
            batch_id=batch_id,
            kind="blocked",
            reason=str(exc),
        )
    try:
        refreshed = chop_batch_store.load_chop_batch(routine, job, batch_id)
        summary = summarize_manifest(refreshed)
    except ChopBatchError:
        summary = {"launched": len(resumed.launches), "remaining": 0}
    if not resumed.waiting:
        interruption_summary = summarize_manifest(manifest)
        emit_batch_notice(
            routine=routine,
            job=job,
            batch_id=batch_id,
            event="interrupted",
            launched=int(
                summary["launched"]
                if resumed.paused
                else interruption_summary["launched"]
            ),
            remaining=int(
                summary["remaining"]
                if resumed.paused
                else interruption_summary["remaining"]
            ),
            clan=clan,
        )
        if not resumed.paused:
            emit_batch_notice(
                routine=routine,
                job=job,
                batch_id=batch_id,
                event="resumed",
                launched=int(summary["launched"]),
                remaining=int(summary["remaining"]),
                clan=clan,
            )
    return ChopBatchRecoveryResult(
        routine=routine,
        job=job,
        batch_id=batch_id,
        kind="typed",
        launched=tuple(resumed.launches),
        paused=bool(resumed.paused),
    )
