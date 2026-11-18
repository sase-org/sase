"""Shared recovery entry point for interrupted chop launch batches.

Resume is continuation of the already accepted run: reconcile pending
manifests before routine guards, reuse the original run ID and agent
identities, and never rerun job scripts or allocate another clan. An
explicit clan-generation kill persists cancellation before any signal or
artifact work so recovery permanently discards the remaining intent.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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
    is still ``pending`` (the stop landed in the spawn/ack window): a
    record for this routine/job/run whose proposal index (or non-empty
    proposal id) matches the member is ``matched_spawn``. ``cl_name`` is
    the project name or VCS ref, never a member identity, so it is never
    compared here. A live or visible agent that owns the name without
    that linkage is a ``foreign_conflict`` and is never relaunched under
    a new identity. The durable name registry tells a provably unspawned
    reservation (``reservation_only``, which may relaunch after its
    reserver died) from a reservation whose reserving process is still
    alive (``live_owner``). A PID alone is never launch proof. Absent
    observations mean the caller proved no reservation or spawn evidence
    exists, so the member is safe to launch.
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
    linked_indexes: set[int] = set()
    linked_proposal_ids: set[str] = set()
    for record in records:
        proposal_index = getattr(record, "proposal_index", None)
        if isinstance(proposal_index, int) and not isinstance(proposal_index, bool):
            linked_indexes.add(proposal_index)
        proposal_id = getattr(record, "proposal_id", "")
        if isinstance(proposal_id, str) and proposal_id:
            linked_proposal_ids.add(proposal_id)
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
        source_index = member.get("source_index")
        proposal_id = member.get("proposal_id")
        linked = (
            isinstance(source_index, int)
            and not isinstance(source_index, bool)
            and source_index in linked_indexes
        ) or (
            isinstance(proposal_id, str)
            and bool(proposal_id)
            and proposal_id in linked_proposal_ids
        )
        if linked:
            observations.append({"agent_name": name, "observation": "matched_spawn"})
        elif name in live_names or _name_has_foreign_owner(name):
            observations.append({"agent_name": name, "observation": "foreign_conflict"})
        else:
            entry = _lookup_registry_entry(name)
            if entry is None:
                continue
            if _registry_reservation_is_live(entry):
                observations.append({"agent_name": name, "observation": "live_owner"})
            else:
                observations.append(
                    {"agent_name": name, "observation": "reservation_only"}
                )
    return observations


def _lookup_registry_entry(name: str) -> dict[str, Any] | None:
    """Return the durable registry entry reserving *name*, if any."""
    try:
        from sase.agent.names import lookup_registered_name

        entry = lookup_registered_name(name)
    except Exception:
        return None
    return entry if isinstance(entry, dict) else None


def _name_has_foreign_owner(name: str) -> bool:
    """Return whether *name* sits inside a reserved foreign owner namespace."""
    try:
        from sase.agent.names import get_blocked_local_namespace_roots

        blocked = get_blocked_local_namespace_roots()
    except Exception:
        return False
    if not isinstance(blocked, Mapping):
        return False
    return any(
        name == root or name.startswith(f"{root}.")
        for root in blocked
        if isinstance(root, str) and root
    )


def _registry_reservation_is_live(entry: Mapping[str, Any]) -> bool:
    """Return whether the process behind a registry reservation is alive.

    Liveness is proven through the reservation's artifact metadata PID, so
    a planned reservation that never published artifacts (a reserver that
    died before spawn, or a claim no live process can substantiate) reads
    as unspawned. A racing live executor holding only a planned
    reservation is indistinguishable here; batch ownership (a later phase)
    closes that race.
    """
    artifacts_dir = entry.get("artifacts_dir")
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return False
    try:
        from sase.agent.names._common import is_process_alive

        directory = Path(artifacts_dir)
        raw = (directory / "agent_meta.json").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    try:
        import json

        meta = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(meta, dict):
        return False
    try:
        return bool(is_process_alive(meta, directory))
    except Exception:
        return False


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
    _pending_resumed_launches: list[dict[str, Any]] = []

    def _dispatch_member(
        member: dict[str, Any], *, before_spawn: Any, on_spawn_recorded: Any
    ) -> Any:
        launcher = launch_agent_from_cwd_fn or launch_agents_from_cwd_fn
        if launcher is None:
            raise ChopBatchError("no launcher available for ordinary batch recovery")
        prompt, wait_name, _effective_ref = _replay_prompt(member, manifest)
        env = _replay_env(routine, job, batch_id, member, prompt)

        def _before(
            _segment: int, _slot: int, request: Any, _membership: Any | None
        ) -> None:
            before_spawn(request)

        def _recorded(
            _segment: int, _slot: int, record: Any, _membership: Any | None
        ) -> None:
            _merge_record = _resumed_launch_descriptor(
                member, record, wait_name, _effective_ref
            )
            if _merge_record is not None:
                _pending_resumed_launches.append(_merge_record)
            on_spawn_recorded(record)

        kwargs: dict[str, Any] = {
            "extra_env": env,
            "before_agent_spawn": _before,
            "on_agent_launch_recorded": _recorded,
            "pause_requested_fn": pause_requested_fn,
        }
        if _launcher_supports_kwarg(launcher, "origin"):
            # Resumed agents are machine-generated continuations of the
            # accepted run, exactly like the first-run dispatch.
            kwargs["origin"] = "generated"
        results = launcher(prompt, **kwargs)
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
    _merge_resumed_launches_into_run(routine, job, batch_id, _pending_resumed_launches)
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


def _launcher_supports_kwarg(function: Callable[..., Any], name: str) -> bool:
    """Return whether *function* accepts keyword argument *name*."""
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return True
    parameters = signature.parameters.values()
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return True
    return name in signature.parameters


def _replay_env(
    routine: str, job: str, run_id: str, member: Mapping[str, Any], prompt: str
) -> dict[str, str]:
    """Rebuild the first-run launch environment for one resumed member.

    The stored proposal env rides underneath fresh chop linkage for the
    original run and proposal index, plus the planned-name marker. Clan
    members additionally pin the recorded clan identity and generation so
    a joiner joins that exact generation and a resumed declarer never
    declares a new one; the single-launch runner honors the pinned plan
    instead of resolving clan membership anew. Only clan-role members
    carry clan directives, so standalone members never receive the payload
    (the runner rejects a membership payload without directives).
    """
    from .chop_agents import build_chop_launch_env

    env = dict(member.get("env") or {})
    source_index = member.get("source_index")
    proposal_id = member.get("proposal_id")
    env.update(
        build_chop_launch_env(
            lumberjack_name=routine,
            chop_name=job,
            prompt=prompt or None,
            run_id=run_id,
            proposal_index=(
                source_index
                if isinstance(source_index, int) and not isinstance(source_index, bool)
                else None
            ),
            proposal_id=(
                proposal_id if isinstance(proposal_id, str) and proposal_id else None
            ),
        )
    )
    agent_name = str(member.get("agent_name") or "")
    if agent_name:
        env.setdefault("SASE_AGENT_PLANNED_NAME", agent_name)
    if str(member.get("launch_role") or "") in {"declare", "join"}:
        clan = member.get("clan")
        generation = member.get("clan_generation")
        if (
            isinstance(clan, str)
            and clan
            and isinstance(generation, str)
            and generation
        ):
            try:
                from sase.agent.clan_membership import (
                    CLAN_MEMBERSHIP_ENV,
                    ClanMembershipPlan,
                    encode_clan_membership_plan,
                )

                env[CLAN_MEMBERSHIP_ENV] = encode_clan_membership_plan(
                    ClanMembershipPlan(clan_name=clan, generation=generation)
                )
            except Exception:
                pass
    return env


def _replay_prompt(
    member: Mapping[str, Any], manifest: Mapping[str, Any]
) -> tuple[str, str | None, int | str | None]:
    """Return the replay prompt, resolved wait name, and effective wait ref.

    The wait reference is rewired exactly as the first run does when an
    earlier member was skipped: the stored reference is resolved through
    journal statuses, so a dependent of a skipped member waits on the
    skipped member's own effective wait instead of a name that will never
    launch. A resumed declarer is rewritten as a joiner of the recorded
    clan, since the clan already exists.
    """
    prompt = str(member.get("prompt") or "")
    members = [
        item for item in manifest.get("members", []) if isinstance(item, Mapping)
    ]
    names_by_index: dict[int, str] = {}
    names_by_id: dict[str, str] = {}
    for item in members:
        agent_name = str(item.get("agent_name") or "")
        source_index = item.get("source_index")
        if (
            isinstance(source_index, int)
            and not isinstance(source_index, bool)
            and agent_name
        ):
            names_by_index[source_index] = agent_name
        item_proposal_id = item.get("proposal_id")
        if isinstance(item_proposal_id, str) and item_proposal_id and agent_name:
            names_by_id[item_proposal_id] = agent_name
    original_ref = _stored_wait_ref(member, members)
    effective_ref = _effective_wait_ref(member, members)
    original_wait_name = _resolve_wait_to_name(
        original_ref, names_by_index, names_by_id
    )
    wait_name = _resolve_wait_to_name(effective_ref, names_by_index, names_by_id)
    if wait_name != original_wait_name:
        prompt = _rewrite_wait_line(member, prompt, original_wait_name, wait_name)
    if str(member.get("launch_role") or "") == "declare":
        prompt = _rewrite_declare_as_join(member, prompt)
    return prompt, wait_name, effective_ref


def _stored_wait_ref(
    member: Mapping[str, Any], ordered_members: Sequence[Mapping[str, Any]]
) -> int | str | None:
    """Return the member's stored wait reference in first-run shape.

    Manifest creation maps integer wait references to member positions;
    invert that mapping back to the referenced proposal index here.
    """
    ref = member.get("wait_on")
    if isinstance(ref, bool):
        return None
    if isinstance(ref, int):
        if 0 <= ref < len(ordered_members):
            target = ordered_members[ref]
            source_index = target.get("source_index")
            if isinstance(source_index, int) and not isinstance(source_index, bool):
                return source_index
        return None
    if isinstance(ref, str) and ref:
        return ref
    return None


def _effective_wait_ref(
    member: Mapping[str, Any],
    ordered_members: Sequence[Mapping[str, Any]],
) -> int | str | None:
    """Mirror the first-run skip rewiring for one member's wait reference."""
    members = list(ordered_members)
    indices_by_id: dict[str, int] = {}
    for item in members:
        item_proposal_id = item.get("proposal_id")
        source_index = item.get("source_index")
        if (
            isinstance(item_proposal_id, str)
            and item_proposal_id
            and isinstance(source_index, int)
            and not isinstance(source_index, bool)
        ):
            indices_by_id.setdefault(item_proposal_id, source_index)
    skipped: set[int] = set()
    for item in members:
        if str(item.get("status") or "") != "skipped":
            continue
        source_index = item.get("source_index")
        if isinstance(source_index, int) and not isinstance(source_index, bool):
            skipped.add(source_index)
    effective_by_source: dict[int, int | str | None] = {}
    for item in members:
        source_index = item.get("source_index")
        if not isinstance(source_index, int) or isinstance(source_index, bool):
            continue
        ref = _stored_wait_ref(item, members)
        dependency: int | None = None
        if isinstance(ref, int) and not isinstance(ref, bool):
            dependency = ref
        elif isinstance(ref, str) and ref:
            dependency = indices_by_id.get(ref)
        if dependency is not None and dependency in skipped:
            effective_by_source[source_index] = effective_by_source.get(dependency, ref)
        else:
            effective_by_source[source_index] = ref
    source_index = member.get("source_index")
    if isinstance(source_index, int) and not isinstance(source_index, bool):
        return effective_by_source.get(source_index, _stored_wait_ref(member, members))
    return _stored_wait_ref(member, members)


def _resolve_wait_to_name(
    ref: int | str | None,
    names_by_index: Mapping[int, str],
    names_by_id: Mapping[str, str],
) -> str | None:
    """Resolve a wait reference to its agent name, like the first run."""
    if ref is None:
        return None
    try:
        from sase.axe.chop_proposal_models import resolve_wait_name

        return resolve_wait_name(ref, names_by_index, names_by_id)
    except KeyError:
        return None
    except Exception:
        return None


def _rewrite_wait_line(
    member: Mapping[str, Any],
    prompt: str,
    original_wait_name: str | None,
    new_wait_name: str | None,
) -> str:
    """Replace, insert, or drop the scaffolded ``%wait`` line of a prompt.

    The scaffold header has a computable shape (workspace line, ``%id``
    line(s), optional ``%model``/``%effort`` lines, an optional ``%queue``
    line, then the ``%wait`` line) followed by the raw proposal body, so
    the rewrite touches only the scaffold line and never body text. An
    unrecognized shape falls back to the stored prompt unchanged.
    """
    lines = prompt.split("\n")
    id_lines = 2 if str(member.get("launch_role") or "") == "declare" else 1
    header = 1 + id_lines
    if member.get("model"):
        header += 1
    if member.get("effort"):
        header += 1
    if len(lines) <= header:
        return prompt
    if not lines[0].startswith("#"):
        return prompt
    for offset in range(1, 1 + id_lines):
        if not lines[offset].startswith("%id"):
            return prompt
    if lines[header].startswith("%queue("):
        header += 1
        if len(lines) <= header:
            return prompt
    if original_wait_name is not None:
        if not lines[header].startswith("%wait:"):
            return prompt
        if new_wait_name is None:
            del lines[header]
        else:
            lines[header] = f"%wait:{new_wait_name}"
    elif new_wait_name is not None:
        lines.insert(header, f"%wait:{new_wait_name}")
    else:
        return prompt
    return "\n".join(lines)


def _rewrite_declare_as_join(member: Mapping[str, Any], prompt: str) -> str:
    """Rewrite a resumed declarer's ``%clan`` line as a clan join line.

    The clan already exists with the recorded generation (pinned through
    the replay env), so replaying the declaration would fail closed. The
    member rejoins under its recorded identity instead.
    """
    clan = member.get("clan")
    agent_name = str(member.get("agent_name") or "")
    if (
        not isinstance(clan, str)
        or not clan
        or not agent_name.startswith(f"{clan}.")
        or len(agent_name) <= len(clan) + 1
    ):
        return prompt
    lines = prompt.split("\n")
    if len(lines) < 3 or not lines[0].startswith("#"):
        return prompt
    if not lines[2].startswith("%clan("):
        return prompt
    member_id = agent_name[len(clan) + 1 :]
    lines[2] = f"%id({member_id}, clan={clan})"
    return "\n".join(lines)


def _resumed_launch_descriptor(
    member: Mapping[str, Any],
    record: Any,
    wait_name: str | None,
    effective_ref: int | str | None = None,
) -> dict[str, Any] | None:
    """Build a first-run-shaped launch descriptor for a resumed launch."""
    try:
        result = getattr(record, "result", None)
        payload = result if result is not None else record
        pid = getattr(payload, "pid", None)
        if not isinstance(pid, int) or isinstance(pid, bool):
            return None
        source_index = member.get("source_index")
        proposal_id = member.get("proposal_id")
        agent_name = str(
            getattr(payload, "agent_name", "") or member.get("agent_name") or ""
        )
        if not agent_name:
            return None
        clan = member.get("clan")
        clan_name = clan if isinstance(clan, str) and clan else None
        member_id: str | None = None
        if clan_name is not None and agent_name.startswith(f"{clan_name}."):
            member_id = agent_name[len(clan_name) + 1 :] or None
        try:
            from sase.core.process_identity import process_identity_token

            identity = process_identity_token(pid)
        except Exception:
            identity = ""
        timestamp = str(getattr(payload, "timestamp", "") or "")
        try:
            from sase.artifacts import convert_timestamp_to_artifacts_format

            artifacts_timestamp = (
                convert_timestamp_to_artifacts_format(timestamp) if timestamp else ""
            )
        except Exception:
            artifacts_timestamp = ""
        try:
            workspace_num = int(getattr(payload, "workspace_num", 0) or 0)
        except (TypeError, ValueError):
            workspace_num = 0
        descriptor: dict[str, Any] = {
            "index": source_index,
            "id": proposal_id if isinstance(proposal_id, str) else None,
            "agent_name": agent_name,
            "clan": clan_name,
            "member_id": member_id,
            "pid": pid,
            "process_identity": identity,
            "workspace": str(member.get("workspace") or ""),
            "workspace_num": workspace_num,
            "workspace_dir": str(getattr(payload, "workspace_dir", "") or ""),
            "project_name": str(getattr(payload, "project_name", "") or ""),
            "workflow_name": str(getattr(payload, "workflow_name", "") or ""),
            "patch_name": str(getattr(payload, "cl_name", "") or ""),
            "cl_name": str(getattr(payload, "cl_name", "") or ""),
            "timestamp": timestamp,
            "artifacts_timestamp": artifacts_timestamp,
            "artifacts_dir": str(getattr(payload, "artifacts_dir", "") or ""),
            "dedupe_key": member.get("dedupe_key"),
            "wait_on": effective_ref,
            "wait_name": wait_name,
        }
        return descriptor
    except Exception:
        return None


def _merge_resumed_launches_into_run(
    routine: str, job: str, batch_id: str, launches: Sequence[Mapping[str, Any]]
) -> None:
    """Merge resumed launch descriptors into the original run history once.

    Entries are keyed by ``(index, agent_name, pid)`` so a retried merge
    never duplicates history; finalization, checkpoints, and once-per
    bookkeeping then see every member of the run. Best effort: a missing
    run entry never fails recovery.
    """
    if not launches:
        return
    try:
        from .state import atomic_write_json, chop_run_meta_path, read_json

        meta_path = chop_run_meta_path(routine, job, batch_id)
        data = read_json(meta_path)
    except Exception:
        return
    if not isinstance(data, dict):
        return
    existing = data.get("launches")
    if not isinstance(existing, list):
        existing = []
    seen = set()
    for entry in existing:
        if isinstance(entry, Mapping):
            seen.add(
                (
                    entry.get("index"),
                    str(entry.get("agent_name") or ""),
                    entry.get("pid"),
                )
            )
    merged = list(existing)
    changed = False
    for launch in launches:
        if not isinstance(launch, Mapping):
            continue
        key = (
            launch.get("index"),
            str(launch.get("agent_name") or ""),
            launch.get("pid"),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(launch))
        changed = True
    if not changed:
        return
    try:
        updated = dict(data)
        updated["launches"] = merged
        atomic_write_json(meta_path, updated)
    except Exception:
        pass


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
