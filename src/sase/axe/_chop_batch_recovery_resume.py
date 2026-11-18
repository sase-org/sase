"""Resume ordinary and typed chop batches after interruption."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from . import chop_batch_store
from ._chop_batch_recovery_observations import collect_spawn_observations
from ._chop_batch_recovery_shared import (
    ChopBatchRecoveryResult,
    batch_clan,
    batch_needs_resume,
    emit_batch_notice,
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
    clan = batch_clan(manifest)
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
        prompt, wait_name, effective_ref = _replay_prompt(member, manifest)
        env = _replay_env(routine, job, batch_id, member, prompt)

        def _before(
            _segment: int, _slot: int, request: Any, _membership: Any | None
        ) -> None:
            before_spawn(request)

        def _recorded(
            _segment: int, _slot: int, record: Any, _membership: Any | None
        ) -> None:
            merge_record = _resumed_launch_descriptor(
                member, record, wait_name, effective_ref
            )
            if merge_record is not None:
                _pending_resumed_launches.append(merge_record)
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
        emit_batch_notice(
            routine=routine,
            job=job,
            batch_id=batch_id,
            event="interrupted",
            launched=notice_summary["launched"],
            remaining=notice_summary["remaining"],
            clan=clan,
        )
        if not replay.paused:
            emit_batch_notice(
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
    member: Mapping[str, Any], ordered_members: Sequence[Mapping[str, Any]]
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
        summary = _summarize_manifest(refreshed)
    except ChopBatchError:
        summary = {"launched": len(resumed.launches), "remaining": 0}
    if not resumed.waiting:
        interruption_summary = _summarize_manifest(manifest)
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
