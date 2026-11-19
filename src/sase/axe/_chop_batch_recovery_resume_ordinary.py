"""Resume ordinary chop batches, replaying their accepted launch context."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from types import SimpleNamespace
from typing import Any

from . import chop_batch_store
from ._chop_batch_recovery_observations import collect_spawn_observations
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


def recover_ordinary_batch(
    routine: str,
    job: str,
    batch_id: str,
    manifest: Mapping[str, Any],
    *,
    launch_agents_from_cwd_fn: Callable[..., Any] | None,
    launch_agent_from_cwd_fn: Callable[..., Any] | None,
    pause_requested_fn: Callable[[], bool] | None,
) -> ChopBatchRecoveryResult:
    from .chop_batch_replay import ChopBatchReplayResult, replay_ordinary_chop_batch

    if not chop_batch_store.acquire_chop_batch_ownership(
        routine, job, batch_id, owner="ordinary-recovery"
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
        from ._chop_batch_recovery_observations import (
            collect_spawn_observations_with_completeness,
        )

        observations, observations_complete, incomplete_reason = (
            collect_spawn_observations_with_completeness(routine, job, manifest)
        )
        if not observations_complete:
            return ChopBatchRecoveryResult(
                routine=routine,
                job=job,
                batch_id=batch_id,
                kind="blocked",
                reason=(
                    "spawn evidence is incomplete; holding without dispatch: "
                    f"{incomplete_reason or 'unreadable evidence'}"
                ),
            )
        clan = batch_clan(manifest)
        initial_summary = summarize_manifest(manifest)
        deliver_pending_batch_notices(routine, job, batch_id)
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
        episode_id = pending_interruption_episode(routine, job, batch_id)
        recovery_evidence = (
            interruption_summary["launched"] > 0
            or matched_pending > 0
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
                launched=interruption_summary["launched"],
                remaining=interruption_summary["remaining"],
                clan=clan,
            )
        if episode_id is not None:
            prepare_batch_notice(
                routine=routine,
                job=job,
                batch_id=batch_id,
                event="resumed",
                launched=interruption_summary["launched"],
                remaining=interruption_summary["remaining"],
                clan=clan,
                episode_id=episode_id,
            )
        pending_resumed_launches: list[dict[str, Any]] = []

        def dispatch_member(
            member: dict[str, Any], *, before_spawn: Any, on_spawn_recorded: Any
        ) -> Any:
            launcher = launch_agent_from_cwd_fn or launch_agents_from_cwd_fn
            if launcher is None:
                raise ChopBatchError(
                    "no launcher available for ordinary batch recovery"
                )
            prompt, wait_name, effective_ref = _replay_prompt(member, manifest)
            env = _replay_env(routine, job, batch_id, member, prompt)

            def before(
                _segment: int, _slot: int, request: Any, _membership: Any | None
            ) -> None:
                before_spawn(request)

            def recorded(
                _segment: int, _slot: int, record: Any, _membership: Any | None
            ) -> None:
                merge_record = _resumed_launch_descriptor(
                    member, record, wait_name, effective_ref
                )
                if merge_record is not None:
                    pending_resumed_launches.append(merge_record)
                on_spawn_recorded(record)

            kwargs: dict[str, Any] = {
                "extra_env": env,
                "before_agent_spawn": before,
                "on_agent_launch_recorded": recorded,
                "pause_requested_fn": pause_requested_fn,
            }
            if _launcher_supports_kwarg(launcher, "origin"):
                kwargs["origin"] = "generated"
            results = launcher(prompt, **kwargs)
            if isinstance(results, list):
                return results[0] if results else None
            return results

        ownership_delegated = True
        try:
            replay: ChopBatchReplayResult = replay_ordinary_chop_batch(
                routine,
                job,
                batch_id,
                observations=observations,
                observations_are_complete=True,
                dispatch_member=dispatch_member,
                pause_requested_fn=pause_requested_fn,
                ownership_acquired=True,
            )
        finally:
            # Take release duty back before the history merge and finish
            # notices: replay no longer retires a delegated batch, so the
            # outbox stays authoritative until the finish notice is delivered.
            ownership_delegated = False
        merge_resumed_launches_into_run(
            routine,
            job,
            batch_id,
            [
                *pending_resumed_launches,
                *backfill_launched_history_descriptors(
                    routine, job, batch_id, replay.already_launched
                ),
            ],
        )
        refreshed = chop_batch_store.load_chop_batch(routine, job, batch_id)
        summary = summarize_manifest(refreshed)
        cancelled = refreshed.get("status") == "cancelled"
        if episode_id is not None:
            emit_batch_notice(
                routine=routine,
                job=job,
                batch_id=batch_id,
                event="resumed",
                launched=summary["launched"],
                remaining=summary["remaining"],
                clan=clan,
                episode_id=episode_id,
            )
        if cancelled:
            emit_batch_notice(
                routine=routine,
                job=job,
                batch_id=batch_id,
                event="cancelled",
                launched=summary["launched"],
                remaining=summary["remaining"],
                clan=clan,
                reason="explicit clan kill",
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


def _launcher_supports_kwarg(function: Callable[..., Any], name: str) -> bool:
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


def backfill_launched_history_descriptors(
    routine: str,
    job: str,
    batch_id: str,
    already_launched: Sequence[int],
) -> list[dict[str, Any]]:
    """Describe journal-launched members whose launch predates this recovery.

    A member acknowledged before the interruption never passes through this
    pass's launcher, so no in-memory launch record exists for it. Its durable
    chop-agent linkage record carries the spawn pid; combining that pid with
    the journal member rebuilds the same launch descriptor shape the run
    history merge dedupes on, so the original run's history lists every
    member exactly once. Members without linkage, or whose linkage lacks a
    pid, are skipped rather than fabricated, and any lookup failure degrades
    to no backfill so history can never break a resume.
    """
    try:
        indexes = [
            int(index)
            for index in already_launched
            if isinstance(index, int) and not isinstance(index, bool)
        ]
        if not indexes:
            return []
        manifest = chop_batch_store.load_chop_batch(routine, job, batch_id)
        members = manifest.get("members")
        if not isinstance(members, list):
            return []
        from .chop_agents import get_chop_agent_records

        records = get_chop_agent_records(routine, chop_name=job, run_id=batch_id)
        by_index: dict[int, Any] = {}
        by_proposal_id: dict[str, Any] = {}
        for record in records or []:
            proposal_index = getattr(record, "proposal_index", None)
            if isinstance(proposal_index, int) and not isinstance(proposal_index, bool):
                by_index.setdefault(proposal_index, record)
            proposal_id = getattr(record, "proposal_id", "")
            if isinstance(proposal_id, str) and proposal_id:
                by_proposal_id.setdefault(proposal_id, record)
        descriptors: list[dict[str, Any]] = []
        for member_index in indexes:
            if not 0 <= member_index < len(members):
                continue
            member = members[member_index]
            if not isinstance(member, Mapping):
                continue
            if str(member.get("status") or "") != "launched":
                continue
            linkage: Any = None
            source_index = member.get("source_index")
            if isinstance(source_index, int) and not isinstance(source_index, bool):
                linkage = by_index.get(source_index)
            if linkage is None:
                member_proposal_id = member.get("proposal_id")
                if isinstance(member_proposal_id, str) and member_proposal_id:
                    linkage = by_proposal_id.get(member_proposal_id)
            if linkage is None:
                continue
            pid = getattr(linkage, "pid", None)
            if not isinstance(pid, int) or isinstance(pid, bool):
                continue
            try:
                workspace_num = int(getattr(linkage, "workspace_num", 0) or 0)
            except (TypeError, ValueError):
                workspace_num = 0
            payload = SimpleNamespace(
                agent_name=str(member.get("agent_name") or ""),
                pid=pid,
                workspace_num=workspace_num,
                workspace_dir="",
                project_name=str(getattr(linkage, "project_name", "") or ""),
                workflow_name=str(getattr(linkage, "workflow_name", "") or ""),
                cl_name=str(getattr(linkage, "cl_name", "") or ""),
                timestamp=str(getattr(linkage, "started_at", "") or ""),
                artifacts_dir="",
            )
            try:
                _, wait_name, effective_ref = _replay_prompt(member, manifest)
            except Exception:
                continue
            try:
                descriptor = _resumed_launch_descriptor(
                    member, payload, wait_name, effective_ref
                )
            except Exception:
                continue
            if descriptor is not None:
                descriptors.append(descriptor)
        return descriptors
    except Exception:
        return []


def merge_resumed_launches_into_run(
    routine: str, job: str, batch_id: str, launches: Sequence[Mapping[str, Any]]
) -> None:
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
