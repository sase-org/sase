"""Shared recovery entry point for interrupted chop launch batches.

Resume is continuation of the already accepted run: reconcile pending
manifests before routine guards, reuse the original run ID and agent
identities, and never rerun job scripts or allocate another clan. An
explicit clan-generation kill persists cancellation before any signal or
artifact work so recovery permanently discards the remaining intent.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sase.core.time import get_timezone

from . import chop_batch_store
from .chop_batch_store import ChopBatchError


@dataclass(frozen=True)
class ChopBatchRecoveryResult:
    """Outcome of attempting recovery for one stored batch."""

    routine: str
    job: str
    batch_id: str
    kind: str  # "ordinary", "typed", "skipped", "blocked", "cancelled"
    launched: tuple[Any, ...] = ()
    already_launched: tuple[int, ...] = ()
    blocked: tuple[dict[str, Any], ...] = ()
    paused: bool = False
    reason: str | None = None


def has_unfinished_chop_batch(routine: str, job: str) -> bool:
    """Return whether any stored batch still owns pending dispatch work."""
    try:
        batches = chop_batch_store.list_pending_chop_batches(routine, job)
    except Exception:
        return False
    for manifest in batches:
        if _batch_needs_resume(manifest):
            return True
    return False


def pending_batch_for_run(routine: str, job: str, run_id: str) -> dict[str, Any] | None:
    """Return the stored batch for one run, if it still owns dispatch work."""
    try:
        manifest = chop_batch_store.load_chop_batch(routine, job, run_id)
    except ChopBatchError:
        return None
    if not _batch_needs_resume(manifest):
        return None
    return manifest


def _batch_needs_resume(manifest: Mapping[str, Any]) -> bool:
    status = str(manifest.get("status") or "open")
    if status in {"cancelled", "complete"}:
        return False
    members = manifest.get("members")
    if not isinstance(members, list):
        return False
    return any(
        str(item.get("status") or "pending") in {"pending", "dispatching"}
        for item in members
        if isinstance(item, Mapping)
    )


def collect_spawn_observations(
    routine: str, job: str, manifest: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Build the complete spawn-evidence snapshot for one batch.

    Durable chop-agent linkage proves a launch even when the member row
    is still ``pending`` (the stop landed in the spawn/ack window). A
    live agent name without linkage is reported as reservation-only so
    the reconciler retries it under the original identity; an unrelated
    live owner of the same name is reported as a foreign conflict.
    Absent observations mean the caller proved no reservation or spawn
    evidence exists, so the member is safe to launch.
    """
    from .chop_agents import get_chop_agent_records

    members = manifest.get("members")
    if not isinstance(members, list):
        return []
    batch_id = str(manifest.get("batch_id") or "")
    run = manifest.get("run")
    run_id = batch_id
    if isinstance(run, Mapping):
        run_id = str(run.get("run_id") or batch_id)
    try:
        records = get_chop_agent_records(routine, chop_name=job, run_id=run_id)
    except Exception:
        records = []
    recorded_names = {str(record.cl_name) for record in records}
    # Also match on the agent-name prefix: records carry the clan name while
    # members carry exact member names.
    try:
        from sase.agent.names import get_active_agent_names

        live_names = set(get_active_agent_names())
    except Exception:
        live_names = set()
    observations: list[dict[str, Any]] = []
    for member in members:
        if not isinstance(member, Mapping):
            continue
        status = str(member.get("status") or "pending")
        if status not in {"pending", "dispatching"}:
            continue
        name = str(member.get("agent_name") or "")
        if not name:
            continue
        if name in recorded_names or any(
            name == str(getattr(record, "cl_name", "") or "")
            or name.startswith(str(getattr(record, "cl_name", "") or "") + "-")
            or str(getattr(record, "cl_name", "") or "").startswith(name)
            for record in records
        ):
            observations.append({"agent_name": name, "observation": "matched_spawn"})
        elif name in live_names:
            observations.append({"agent_name": name, "observation": "reservation_only"})
    return observations


def _emit_batch_notice(
    *,
    routine: str,
    job: str,
    batch_id: str,
    event: str,
    launched: int,
    remaining: int,
    clan: str | None = None,
) -> None:
    """Append a deduplicated run log line and notification for one batch event."""
    timestamp = datetime.now(get_timezone()).isoformat()
    clan_part = f" clan {clan}" if clan else ""
    line = (
        f"Chop batch {event}: routine {routine} job {job} run {batch_id}{clan_part}: "
        f"{launched} launched, {remaining} remaining (at {timestamp}).\n"
    )
    try:
        from .state import append_chop_run_output

        append_chop_run_output(routine, job, batch_id, line)
    except Exception:
        pass
    try:
        from uuid import uuid4

        from sase.notifications.models import Notification
        from sase.notifications.store import upsert_notification

        dedup_key = f"chop-batch:{event}:{routine}:{job}:{batch_id}"
        notes = [
            f"Chop launch batch {event}: {routine}/{job} run {batch_id}.",
            f"{launched} launched, {remaining} remaining.",
        ]
        if clan:
            notes.append(f"Clan: {clan}.")
        if event == "interrupted":
            notes.append("The batch will resume automatically on the next tick.")
        elif event == "resumed":
            notes.append("Remaining members resumed under their original identities.")
        elif event == "cancelled":
            notes.append(
                "Remaining launch intent was discarded by an explicit clan kill."
            )
        notification = Notification(
            id=str(uuid4()),
            timestamp=timestamp,
            sender="chop-batch-recovery",
            icon="!",
            color="#D14343" if event in {"interrupted", "cancelled"} else "#2E7D32",
            notes=notes,
            files=[],
            tags=["chop", "batch", event],
            dedup_key=dedup_key,
        )
        upsert_notification(
            notification,
            plus_one_note=f"Still {event}",
            plus_one_timestamp=timestamp,
        )
    except Exception:
        pass


def _batch_clan(manifest: Mapping[str, Any]) -> str | None:
    for key in ("clan", "clan_name"):
        value = manifest.get(key)
        if isinstance(value, str) and value:
            return value
    members = manifest.get("members")
    if isinstance(members, list):
        for member in members:
            if isinstance(member, Mapping):
                clan = member.get("clan")
                if isinstance(clan, str) and clan:
                    return clan
    return None


def cancel_chop_batches_for_clan(
    clan: str,
    *,
    generation: str | None = None,
    reason: str,
    routine: str | None = None,
    job: str | None = None,
) -> list[dict[str, Any]]:
    """Persist explicit clan-generation cancellation for matching batches.

    This is the shared backend operation every clan/bulk kill entry point
    must call before member expansion loses the container identity. It
    persists cancellation first so a later recovery permanently discards
    the remaining launch intent, then typed coordinator cancellation
    observes the same state. Killing an individual member must not call
    this; only an explicit clan-container kill does.
    """
    from .state import list_lumberjack_names

    cancelled: list[dict[str, Any]] = []
    if not clan:
        return cancelled
    routines = [routine] if routine else _safe_list_routines(list_lumberjack_names)
    for routine_name in routines:
        jobs = [job] if job else _safe_list_jobs(routine_name)
        for job_name in jobs:
            try:
                batches = chop_batch_store.list_pending_chop_batches(
                    routine_name, job_name
                )
            except Exception:
                continue
            for manifest in batches:
                batch_id = str(manifest.get("batch_id") or "")
                if not batch_id or not _batch_needs_resume(manifest):
                    continue
                if _batch_clan(manifest) != clan:
                    continue
                if generation is not None and not _generation_matches(
                    manifest, generation
                ):
                    continue
                try:
                    updated = chop_batch_store.apply_chop_batch_event(
                        routine_name,
                        job_name,
                        batch_id,
                        "cancel_clan_generation",
                        reason=reason or f"explicit clan kill of {clan}",
                    )
                except ChopBatchError:
                    continue
                _emit_batch_notice(
                    routine=routine_name,
                    job=job_name,
                    batch_id=batch_id,
                    event="cancelled",
                    launched=int(updated.get("counts", {}).get("launched", 0))
                    if isinstance(updated.get("counts"), Mapping)
                    else 0,
                    remaining=0,
                    clan=clan,
                )
                _cancel_linked_typed_bundle(updated, reason=reason)
                cancelled.append(
                    {"routine": routine_name, "job": job_name, "batch_id": batch_id}
                )
    return cancelled


def _safe_list_routines(list_fn: Callable[[], list[str]]) -> list[str]:
    try:
        return list(list_fn())
    except Exception:
        return []


def _safe_list_jobs(routine: str) -> list[str]:
    try:
        from .state import lumberjack_state_dir

        chops_dir = lumberjack_state_dir(routine) / "chops"
        if not chops_dir.exists():
            return []
        return sorted(d.name for d in chops_dir.iterdir() if d.is_dir())
    except Exception:
        return []


def _generation_matches(manifest: Mapping[str, Any], generation: str) -> bool:
    if not generation:
        return True
    stored = manifest.get("clan_generation")
    if isinstance(stored, str) and stored and stored != generation:
        return False
    members = manifest.get("members")
    if isinstance(members, list):
        generations = {
            str(item.get("clan_generation") or "")
            for item in members
            if isinstance(item, Mapping) and item.get("clan_generation")
        }
        if generations and generation not in generations:
            # A reused clan name in another generation must not cancel this batch.
            return False
    return True


def _cancel_linked_typed_bundle(manifest: Mapping[str, Any], *, reason: str) -> None:
    bundle_ref = manifest.get("typed_bundle")
    if not isinstance(bundle_ref, Mapping):
        return
    try:
        from pathlib import Path

        from sase.agent.direct_typed_launch import typed_launch_bundle_dir
        from sase.agent.launch_admission import cancel_typed_launch_request

        bundle_id = str(bundle_ref.get("bundle_id") or "")
        if not bundle_id:
            return
        bundle_dir: Path = typed_launch_bundle_dir(bundle_id)
        try:
            cancel_typed_launch_request(bundle_dir, reason=reason)
        except Exception:
            pass
    except Exception:
        pass


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
            if not batch_id or not _batch_needs_resume(manifest):
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


def _recover_ordinary_batch(
    routine: str,
    job: str,
    batch_id: str,
    manifest: Mapping[str, Any],
    *,
    launch_agents_from_cwd_fn: Callable[..., Any] | None,
    launch_agent_from_cwd_fn: Callable[..., Any] | None,
    pause_requested_fn: Callable[[], bool] | None,
) -> ChopBatchRecoveryResult:
    from .chop_batch_replay import replay_ordinary_chop_batch

    observations = collect_spawn_observations(routine, job, manifest)
    clan = _batch_clan(manifest)
    initial_summary = _summarize_manifest(manifest)
    matched_names = {
        str(item.get("agent_name") or "")
        for item in observations
        if item.get("observation") == "matched_spawn"
    }
    matched_pending = sum(
        1
        for member in manifest.get("members", [])
        if isinstance(member, Mapping)
        and str(member.get("status") or "pending") in {"pending", "dispatching"}
        and str(member.get("agent_name") or "") in matched_names
    )
    interruption_summary = {
        "launched": initial_summary["launched"] + matched_pending,
        "remaining": max(0, initial_summary["remaining"] - matched_pending),
    }

    def _dispatch_member(
        member: dict[str, Any], *, before_spawn: Any, on_spawn_recorded: Any
    ) -> Any:
        launcher = launch_agent_from_cwd_fn or launch_agents_from_cwd_fn
        if launcher is None:
            raise ChopBatchError("no launcher available for ordinary batch recovery")
        prompt = str(member.get("prompt") or "")
        env = dict(member.get("env") or {})
        agent_name = str(member.get("agent_name") or "")
        if agent_name:
            env = dict(env)
            env.setdefault("SASE_AGENT_PLANNED_NAME", agent_name)

        def _before(
            _segment: int, _slot: int, request: Any, _membership: Any | None
        ) -> None:
            before_spawn(request)

        def _recorded(
            _segment: int, _slot: int, record: Any, _membership: Any | None
        ) -> None:
            on_spawn_recorded(record)

        results = launcher(
            prompt,
            extra_env=env,
            before_agent_spawn=_before,
            on_agent_launch_recorded=_recorded,
            pause_requested_fn=pause_requested_fn,
        )
        if isinstance(results, list):
            return results[0] if results else None
        return results

    try:
        replay = replay_ordinary_chop_batch(
            routine,
            job,
            batch_id,
            observations=observations,
            observations_are_complete=True,
            dispatch_member=_dispatch_member,
            pause_requested_fn=pause_requested_fn,
        )
    except ChopBatchError as exc:
        return ChopBatchRecoveryResult(
            routine=routine,
            job=job,
            batch_id=batch_id,
            kind="blocked",
            reason=str(exc),
        )
    refreshed = chop_batch_store.load_chop_batch(routine, job, batch_id)
    summary = _summarize_manifest(refreshed)
    cancelled = refreshed.get("status") == "cancelled"
    if not cancelled:
        notice_summary = summary if replay.paused else interruption_summary
        _emit_batch_notice(
            routine=routine,
            job=job,
            batch_id=batch_id,
            event="interrupted",
            launched=notice_summary["launched"],
            remaining=notice_summary["remaining"],
            clan=clan,
        )
        if not replay.paused:
            _emit_batch_notice(
                routine=routine,
                job=job,
                batch_id=batch_id,
                event="resumed",
                launched=summary["launched"],
                remaining=summary["remaining"],
                clan=clan,
            )
    return ChopBatchRecoveryResult(
        routine=routine,
        job=job,
        batch_id=batch_id,
        launched=tuple(replay.launched),
        already_launched=tuple(replay.already_launched),
        blocked=tuple(replay.blocked),
        paused=bool(replay.paused),
        kind="cancelled" if cancelled else "ordinary",
        reason="batch was explicitly cancelled" if cancelled else None,
    )


def _recover_typed_batch(
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

    clan = _batch_clan(manifest)
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
        summary = _summarize_manifest(refreshed)
    except ChopBatchError:
        summary = {"launched": len(resumed.launches), "remaining": 0}
    if not resumed.waiting:
        interruption_summary = _summarize_manifest(manifest)
        _emit_batch_notice(
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
            _emit_batch_notice(
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


def _summarize_manifest(manifest: Mapping[str, Any]) -> dict[str, int]:
    try:
        from sase.core.axe_chop_facade import summarize_chop_batch

        summary = summarize_chop_batch(dict(manifest))
        counts = summary.get("counts") or {}
        launched = int(counts.get("launched", 0))
        pending = int(counts.get("pending", 0))
        dispatching = int(counts.get("dispatching", 0))
        return {"launched": launched, "remaining": pending + dispatching}
    except Exception:
        members = manifest.get("members")
        launched = 0
        remaining = 0
        if isinstance(members, list):
            for item in members:
                if not isinstance(item, Mapping):
                    continue
                status = str(item.get("status") or "")
                if status == "launched":
                    launched += 1
                elif status in {"pending", "dispatching"}:
                    remaining += 1
        return {"launched": launched, "remaining": remaining}


__all__ = [
    "ChopBatchRecoveryResult",
    "cancel_chop_batches_for_clan",
    "collect_spawn_observations",
    "has_unfinished_chop_batch",
    "pending_batch_for_run",
    "recover_pending_chop_batches",
]
