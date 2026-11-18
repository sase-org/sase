"""Resume ordinary and typed chop batches after interruption."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from . import chop_batch_store
from ._chop_batch_recovery_resume_ordinary import (
    recover_ordinary_batch as _recover_ordinary_batch,
)
from ._chop_batch_recovery_resume_typed import (
    recover_typed_batch as _recover_typed_batch,
)
from ._chop_batch_recovery_shared import (
    ChopBatchRecoveryResult,
    batch_needs_resume,
)
from .chop_batch_store import ChopBatchError


def recover_pending_chop_batches(
    routine: str,
    job: str,
    *,
    launch_agents_from_cwd_fn: Callable[..., Any] | None = None,
    launch_agent_from_cwd_fn: Callable[..., Any] | None = None,
    pause_requested_fn: Callable[[], bool] | None = None,
    dry_run: bool = False,
    jobs: Sequence[str] | None = None,
) -> list[ChopBatchRecoveryResult]:
    """Reconcile pending batches for one routine/job before any new work.

    The same entry point serves routine ticks and manual encounters. It
    never reruns job scripts, consumes fresh triggers, or allocates
    another clan. Disabled or maintenance-held jobs are reported as
    blocked without dispatching. Dry-run paths stay read-only.
    """
    from .maintenance import read_maintenance

    targets = list(jobs) if jobs is not None else [job]
    results: list[ChopBatchRecoveryResult] = []
    try:
        maintenance = read_maintenance()
    except Exception:
        maintenance = None
    for job_name in targets:
        if _job_disabled(job_name, routine):
            results.append(
                ChopBatchRecoveryResult(
                    routine=routine,
                    job=job_name,
                    batch_id="*",
                    kind="blocked",
                    reason=f"job {job_name} is disabled; pending batches held",
                )
            )
            continue
        if maintenance is not None:
            results.append(
                ChopBatchRecoveryResult(
                    routine=routine,
                    job=job_name,
                    batch_id="*",
                    kind="blocked",
                    reason="axe maintenance holds dispatch",
                )
            )
            continue
        try:
            batches = chop_batch_store.list_pending_chop_batches(routine, job_name)
        except Exception:
            continue
        for manifest in batches:
            batch_id = str(manifest.get("batch_id") or "")
            if not batch_id or not batch_needs_resume(manifest):
                continue
            if dry_run:
                results.append(
                    ChopBatchRecoveryResult(
                        routine=routine,
                        job=job_name,
                        batch_id=batch_id,
                        kind="blocked",
                        reason="dry-run holds pending batch without dispatch",
                    )
                )
                continue
            results.append(
                _recover_one_batch(
                    routine,
                    job_name,
                    batch_id,
                    launch_agents_from_cwd_fn=launch_agents_from_cwd_fn,
                    launch_agent_from_cwd_fn=launch_agent_from_cwd_fn,
                    pause_requested_fn=pause_requested_fn,
                )
            )
    return results


def _job_disabled(job_name: str, routine: str) -> bool:
    try:
        from .config import load_axe_config

        config = load_axe_config()
        lumberjacks = getattr(config, "lumberjacks", {}) or {}
        lumberjack = lumberjacks.get(routine)
        if lumberjack is None:
            return False
        for chop in getattr(lumberjack, "chops", []) or []:
            if getattr(chop, "name", None) == job_name:
                return not bool(getattr(chop, "enabled", True))
    except Exception:
        return False
    return False


def _recover_one_batch(
    routine: str,
    job: str,
    batch_id: str,
    *,
    launch_agents_from_cwd_fn: Callable[..., Any] | None,
    launch_agent_from_cwd_fn: Callable[..., Any] | None,
    pause_requested_fn: Callable[[], bool] | None,
) -> ChopBatchRecoveryResult:
    try:
        manifest = chop_batch_store.load_chop_batch(routine, job, batch_id)
    except ChopBatchError as exc:
        return ChopBatchRecoveryResult(
            routine=routine, job=job, batch_id=batch_id, kind="blocked", reason=str(exc)
        )
    if str(manifest.get("status") or "open") == "cancelled":
        return ChopBatchRecoveryResult(
            routine=routine,
            job=job,
            batch_id=batch_id,
            kind="cancelled",
            reason="batch was explicitly cancelled",
        )
    if manifest.get("typed_bundle") is not None:
        return _recover_typed_batch(
            routine,
            job,
            batch_id,
            manifest,
            launch_agents_from_cwd_fn=launch_agents_from_cwd_fn,
            launch_agent_from_cwd_fn=launch_agent_from_cwd_fn,
            pause_requested_fn=pause_requested_fn,
        )
    return _recover_ordinary_batch(
        routine,
        job,
        batch_id,
        manifest,
        launch_agents_from_cwd_fn=launch_agents_from_cwd_fn,
        launch_agent_from_cwd_fn=launch_agent_from_cwd_fn,
        pause_requested_fn=pause_requested_fn,
    )
