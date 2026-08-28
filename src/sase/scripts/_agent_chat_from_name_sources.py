"""Top-level fork-source orchestration for named-agent chat resolution."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import os
from pathlib import Path

from sase.agent.names import (
    find_agent_clan,
    find_agent_family,
    resolve_resume_agent_name,
)
from sase.agent.names._lookup_artifacts import is_success_outcome
from sase.core.agent_tribe import parse_tribe_reference
from sase.core.dismissed_agent_completion import FAILURE_OUTCOMES
from sase.monitor_state import is_real_monitor_member
from sase.procs import ProcRefError, read_procs, resolve_proc_ref
from sase.scripts._agent_chat_from_name_common import (
    completed_response_path,
    find_family_member,
    json_string,
    normalize_name,
    read_json_dict,
    resolve_clan_tribe,
    resolve_default_agent_name,
    validate_readable_transcript,
)
from sase.scripts._agent_chat_from_name_failure import failed_agent_fork_source
from sase.scripts._agent_chat_from_name_family import resolve_family_member_shell
from sase.scripts._agent_chat_from_name_models import (
    ForkClanMemberSource,
    ForkExcludedFamilyMember,
    ForkFamilyMemberSource,
    ForkSource,
)
from sase.scripts._agent_chat_from_name_monitor import resolve_monitor_fork_source
from sase.scripts._agent_chat_from_name_resume import resolve_agent_chat_path
from sase.scripts._agent_chat_from_name_tribe import resolve_tribe_fork_source
from sase.scripts._fork_proc_sources import proc_info_from_proc


def resolve_agent_chat_sources(names: Sequence[str]) -> list[ForkSource]:
    """Resolve and validate every requested parent as one atomic operation."""
    requested_names: list[str | None] = list(names) or [None]
    sources: list[ForkSource] = []
    errors: list[str] = []
    first_parent_by_text: dict[str, int] = {}

    for index, requested_name in enumerate(requested_names, start=1):
        label = requested_name or "<default>"
        if requested_name is not None:
            parent_text = requested_name.strip()
            previous_index = first_parent_by_text.get(parent_text)
            if previous_index is not None:
                errors.append(
                    f"parent {index} ({label}): repeated parent argument "
                    f"{parent_text!r} (already requested as parent "
                    f"{previous_index})"
                )
            else:
                first_parent_by_text[parent_text] = index
        try:
            resolved_name = normalize_name(requested_name)
            if resolved_name is None:
                resolved_name = resolve_default_agent_name()
            source = _resolve_fork_source(resolved_name)
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"parent {index} ({label}): {exc}")
        else:
            sources.append(source)

    if errors:
        raise RuntimeError("Invalid fork parents:\n- " + "\n- ".join(errors))
    return _coalesce_fork_sources(sources)


def _coalesce_fork_sources(sources: Sequence[ForkSource]) -> list[ForkSource]:
    """Keep each canonical transcript or proc once in stable parent/member order.

    Identity is the canonical chat/artifact path for an agent shell and the
    durable proc ID for a proc or monitor shell. A transcript-less entry (a
    failed agent with no saved chat, or a proc source missing its info) never
    claims an identity, so two such entries are never mistakenly coalesced
    together.
    """
    coalesced: list[ForkSource] = []
    seen_identities: set[tuple[str, str]] = set()

    def claim(identity: tuple[str, str] | None) -> bool:
        if identity is None:
            return True
        if identity in seen_identities:
            return False
        seen_identities.add(identity)
        return True

    for source in sources:
        if source.kind in ("agent", "proc"):
            if not claim(_source_identity(source)):
                continue
            coalesced.append(source)
            continue

        unique_members: list[ForkClanMemberSource | ForkFamilyMemberSource] = []
        for member in source.members:
            if not claim(_member_identity(member)):
                continue
            unique_members.append(member)

        if not unique_members:
            continue
        coalesced.append(
            replace(
                source,
                path=unique_members[-1].path,
                members=tuple(unique_members),
            )
        )

    return coalesced


def _source_identity(source: ForkSource) -> tuple[str, str] | None:
    if source.kind == "proc":
        if source.proc is None:
            return None
        return ("proc", source.proc.proc_id)
    if not source.path:
        return None
    return ("path", str(_canonical_transcript_path(source.path)))


def _member_identity(
    member: ForkClanMemberSource | ForkFamilyMemberSource,
) -> tuple[str, str] | None:
    if isinstance(member, ForkFamilyMemberSource) and member.kind == "proc":
        if member.proc is None:
            return None
        return ("proc", member.proc.proc_id)
    if not member.path:
        return None
    return ("path", str(_canonical_transcript_path(member.path)))


def _canonical_transcript_path(path: str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _resolve_fork_source(name: str) -> ForkSource:
    """Resolve *name* to an agent, family, or complete clan source."""
    tribe = parse_tribe_reference(name)
    if tribe is not None:
        return resolve_tribe_fork_source(name, tribe)

    clan = find_agent_clan(name)
    if clan is not None:
        current = _current_artifacts_dir()
        clan_members_for_fork = tuple(
            member
            for member in clan.members
            if not _same_artifacts_dir(member.artifacts_dir, current)
        )
        if not clan_members_for_fork:
            raise RuntimeError(f"No agent with chat history found for: {name}")
        if not all(
            is_success_outcome(member.outcome) for member in clan_members_for_fork
        ):
            done_count = sum(
                is_success_outcome(member.outcome) for member in clan_members_for_fork
            )
            raise RuntimeError(
                f"Clan '{name}' is not complete: "
                f"{done_count}/{len(clan_members_for_fork)} members done"
            )

        clan_members: list[ForkClanMemberSource] = []
        for member in clan_members_for_fork:
            path = completed_response_path(
                member.name,
                member.artifacts_dir,
                archived_completion=member.archived_completion,
                clan_member=True,
            )
            clan_members.append(
                ForkClanMemberSource(
                    name=member.name,
                    path=path,
                    artifact_dir=str(member.artifacts_dir),
                )
            )

        newest_member = max(
            clan_members, key=lambda member: Path(member.artifact_dir).name
        )
        return ForkSource(
            kind="clan",
            name=clan.name,
            path=newest_member.path,
            generation=clan.generation,
            tribe=resolve_clan_tribe(clan),
            members=tuple(clan_members),
        )

    family = find_agent_family(name)
    if family is not None:
        current = _current_artifacts_dir()
        family_members: list[ForkFamilyMemberSource] = []
        excluded: list[ForkExcludedFamilyMember] = []
        for family_member in family.members:
            if _same_artifacts_dir(family_member.artifacts_dir, current):
                continue
            resolved = resolve_family_member_shell(family_member)
            if isinstance(resolved, ForkExcludedFamilyMember):
                excluded.append(resolved)
            else:
                family_members.append(resolved)

        if not family_members:
            raise RuntimeError(f"No agent with chat history found for: {name}")

        return ForkSource(
            kind="family",
            name=family.base_name,
            path=family_members[-1].path,
            members=tuple(family_members),
            excluded=tuple(excluded),
        )

    return _resolve_agent_or_proc_fork_source(name)


def _current_artifacts_dir() -> Path | None:
    current_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not current_artifacts_dir:
        return None
    return Path(current_artifacts_dir).expanduser().resolve(strict=False)


def _same_artifacts_dir(artifacts_dir: Path, current: Path | None) -> bool:
    return (
        current is not None
        and artifacts_dir.expanduser().resolve(strict=False) == current
    )


def _resolve_agent_or_proc_fork_source(name: str) -> ForkSource:
    """Resolve one named agent, falling back to a stand-alone proc shell.

    Existing agent names keep their current meaning: a proc/monitor lookup is
    attempted only once agent resolution fails outright, so a reusable proc
    name never shadows an agent. An ambiguous proc reference is surfaced as an
    actionable error rather than silently falling back to "agent not found".
    """
    try:
        return _resolve_agent_fork_source(name)
    except RuntimeError as agent_error:
        proc_source = _try_resolve_standalone_proc_fork_source(name)
        if proc_source is not None:
            return proc_source
        raise agent_error


def _try_resolve_standalone_proc_fork_source(name: str) -> ForkSource | None:
    try:
        proc = resolve_proc_ref(name, read_procs())
    except ProcRefError as exc:
        if "ambiguous" in str(exc):
            raise RuntimeError(str(exc)) from exc
        return None
    return ForkSource(
        kind="proc",
        name=name,
        path="",
        proc=proc_info_from_proc(proc),
    )


def _resolve_agent_fork_source(name: str) -> ForkSource:
    """Resolve one named agent, including terminal failure context."""
    family_member = find_family_member(name)
    if family_member is not None:
        meta = read_json_dict(family_member.artifacts_dir / "agent_meta.json") or {}
        if is_real_monitor_member(
            json_string(meta, "agent_family_role"),
            json_string(meta, "monitor_id"),
        ):
            return resolve_monitor_fork_source(name, family_member.artifacts_dir)

        done = read_json_dict(family_member.artifacts_dir / "done.json") or {}
        outcome = json_string(done, "outcome") or family_member.outcome
        if outcome in FAILURE_OUTCOMES:
            return failed_agent_fork_source(
                name,
                family_member.artifacts_dir,
                done,
                outcome,
            )

    agent = resolve_resume_agent_name(name)
    if agent is not None:
        artifact_dir = Path(agent.artifacts_dir)
        done = read_json_dict(artifact_dir / "done.json") or {}
        outcome = json_string(done, "outcome") or agent.outcome
        if outcome in FAILURE_OUTCOMES:
            return failed_agent_fork_source(name, artifact_dir, done, outcome)

    source = ForkSource(
        kind="agent",
        name=name,
        path=resolve_agent_chat_path(name),
    )
    validate_readable_transcript(source.name, source.path)
    return source
