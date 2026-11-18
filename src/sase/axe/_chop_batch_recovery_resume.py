"""Resume ordinary and typed chop batches after interruption."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
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
    clear_batch_recovery_hold,
    deliver_pending_batch_notices,
    emit_batch_notice,
    summarize_manifest,
)
from .chop_batch_store import (
    ChopBatchError,
    batch_has_unsettled_cancelled_dispatch,
    retire_chop_batch,
)


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
        try:
            batches = chop_batch_store.list_pending_chop_batches(
                routine,
                job_name,
                repair_index=not dry_run,
                retire_terminal=not dry_run,
            )
        except Exception as exc:
            results.append(
                ChopBatchRecoveryResult(
                    routine=routine,
                    job=job_name,
                    batch_id="*",
                    kind="blocked",
                    reason=f"cannot enumerate pending batches: {exc}",
                )
            )
            continue
        for manifest in batches:
            batch_id = str(manifest.get("batch_id") or "")
            if not batch_id:
                continue
            if dry_run:
                # Strictly read-only: no notice delivery, no index repair,
                # no retirement, no hold emission, no owner acquisition.
                if batch_has_unsettled_cancelled_dispatch(
                    manifest
                ) or batch_needs_resume(manifest):
                    results.append(
                        _blocked_result(
                            routine,
                            job_name,
                            batch_id,
                            manifest,
                            "dry-run holds pending batch without dispatch",
                        )
                    )
                continue
            try:
                deliver_pending_batch_notices(routine, job_name, batch_id)
            except Exception as exc:
                _append_recovery_error(
                    routine,
                    job_name,
                    batch_id,
                    f"could not deliver a saved recovery notice: {exc}",
                )
                result = ChopBatchRecoveryResult(
                    routine=routine,
                    job=job_name,
                    batch_id=batch_id,
                    kind="blocked",
                    reason=f"could not deliver a saved recovery notice: {exc}",
                )
                results.append(result)
                continue
            if batch_has_unsettled_cancelled_dispatch(manifest):
                from ._chop_batch_recovery_cancel_settlement import (
                    recover_cancelled_batch,
                )

                try:
                    result = recover_cancelled_batch(
                        routine, job_name, batch_id, manifest
                    )
                except Exception as exc:
                    result = _blocked_result(
                        routine,
                        job_name,
                        batch_id,
                        manifest,
                        f"cancelled settlement failed: {type(exc).__name__}: {exc}",
                    )
                results.append(result)
                continue
            if not batch_needs_resume(manifest):
                if str(manifest.get("status") or "") in {"complete", "cancelled"}:
                    retire_chop_batch(routine, job_name, batch_id)
                continue
            if _job_disabled(job_name, routine):
                result = _blocked_result(
                    routine,
                    job_name,
                    batch_id,
                    manifest,
                    f"job {job_name} is disabled; pending batch is held",
                )
                _try_emit_recovery_hold(result, manifest)
                results.append(result)
                continue
            if maintenance is not None:
                result = _blocked_result(
                    routine,
                    job_name,
                    batch_id,
                    manifest,
                    "axe maintenance holds dispatch",
                )
                _try_emit_recovery_hold(result, manifest)
                results.append(result)
                continue
            if dry_run:
                results.append(
                    _blocked_result(
                        routine,
                        job_name,
                        batch_id,
                        manifest,
                        "dry-run holds pending batch without dispatch",
                    )
                )
                continue
            try:
                result = _recover_one_batch(
                    routine,
                    job_name,
                    batch_id,
                    launch_agents_from_cwd_fn=launch_agents_from_cwd_fn,
                    launch_agent_from_cwd_fn=launch_agent_from_cwd_fn,
                    pause_requested_fn=pause_requested_fn,
                )
            except Exception as exc:
                result = _blocked_result(
                    routine,
                    job_name,
                    batch_id,
                    manifest,
                    f"recovery failed: {type(exc).__name__}: {exc}",
                )
            visible_hold = _visible_hold_reason(result)
            if visible_hold is not None:
                try:
                    _emit_recovery_hold(result, manifest, reason=visible_hold)
                except Exception as exc:
                    _append_recovery_error(routine, job_name, batch_id, str(exc))
                    result = replace(
                        result,
                        kind="blocked",
                        reason=f"{visible_hold}; notification delivery failed: {exc}",
                    )
            else:
                try:
                    clear_batch_recovery_hold(routine, job_name, batch_id)
                except Exception as exc:
                    _append_recovery_error(
                        routine,
                        job_name,
                        batch_id,
                        f"could not clear recovery hold: {exc}",
                    )
                    result = replace(
                        result,
                        kind="blocked",
                        reason=f"could not clear recovery hold: {exc}",
                    )
            results.append(result)
            try:
                refreshed = chop_batch_store.load_chop_batch(
                    routine, job_name, batch_id
                )
                if str(refreshed.get("status") or "") in {"complete", "cancelled"}:
                    deliver_pending_batch_notices(routine, job_name, batch_id)
                    retire_chop_batch(routine, job_name, batch_id)
            except ChopBatchError:
                pass
    return results


def _blocked_result(
    routine: str,
    job: str,
    batch_id: str,
    manifest: Mapping[str, Any],
    reason: str,
) -> ChopBatchRecoveryResult:
    return ChopBatchRecoveryResult(
        routine=routine,
        job=job,
        batch_id=batch_id,
        kind="blocked",
        blocked=(),
        reason=reason,
    )


def _visible_hold_reason(result: ChopBatchRecoveryResult) -> str | None:
    if result.kind == "blocked":
        reason = result.reason or "recovery is blocked"
        if "already has a live owner" in reason:
            return None
        return reason
    if not result.blocked:
        return None
    visible = [
        item
        for item in result.blocked
        if str(item.get("status") or item.get("observation") or "") != "live_owner"
    ]
    if not visible:
        return None
    return "; ".join(
        str(
            item.get("reason") or item.get("status") or item.get("agent_name") or "held"
        )
        for item in visible
    )


def _emit_recovery_hold(
    result: ChopBatchRecoveryResult,
    manifest: Mapping[str, Any],
    *,
    reason: str | None = None,
) -> None:
    summary = summarize_manifest(manifest)
    reason = reason or result.reason or "recovery is held"
    emit_batch_notice(
        routine=result.routine,
        job=result.job,
        batch_id=result.batch_id,
        event="hold",
        launched=summary["launched"],
        remaining=summary["remaining"],
        clan=_batch_clan_from_manifest(manifest),
        reason=reason,
        hold_key=reason,
    )


def _try_emit_recovery_hold(
    result: ChopBatchRecoveryResult, manifest: Mapping[str, Any]
) -> None:
    try:
        _emit_recovery_hold(result, manifest)
    except Exception as exc:
        _append_recovery_error(result.routine, result.job, result.batch_id, str(exc))


def _batch_clan_from_manifest(manifest: Mapping[str, Any]) -> str | None:
    from ._chop_batch_recovery_shared import batch_clan

    return batch_clan(manifest)


def _append_recovery_error(routine: str, job: str, batch_id: str, reason: str) -> None:
    try:
        from .state import append_chop_run_output

        append_chop_run_output(
            routine,
            job,
            batch_id,
            f"Chop batch recovery error for {routine}/{job} run {batch_id}: {reason}\n",
        )
    except Exception:
        pass


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
    except Exception as exc:
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
