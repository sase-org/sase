"""Resolve the chat transcript path for ``#fork`` workflows."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.names import (
    AgentClan,
    find_agent_clan,
    find_named_agent,
    get_most_recent_agent_name,
    get_reserved_agent_name_map,
    is_agent_name_template,
    require_latest_agent_name_template,
    resolve_agent_name_template_reference,
    resolve_resume_agent_name,
)
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.agent_tribe import parse_tribe_reference
from sase.core.paths import sase_projects_dir
from sase.core.wait_dependency_resolution import (
    TribeCandidate,
    WaitDependencyIndex,
    read_json_dict,
)


@dataclass(frozen=True)
class _ForkClanMemberSource:
    """One completed clan member included in a clan fork source."""

    name: str
    path: str
    artifact_dir: str


@dataclass(frozen=True)
class _ForkSource:
    """One agent conversation or completed clan used by ``#fork``."""

    kind: str
    name: str
    path: str
    generation: str | None = None
    tribe: str | None = None
    members: tuple[_ForkClanMemberSource, ...] = ()

    def to_json_data(self) -> dict[str, object]:
        """Return the stable wire shape consumed by the fork history builder."""
        if self.kind == "agent":
            return {"kind": self.kind, "name": self.name, "path": self.path}
        return {
            "kind": self.kind,
            "name": self.name,
            "generation": self.generation,
            "tribe": self.tribe,
            "members": [
                {
                    "name": member.name,
                    "path": member.path,
                    "artifact_dir": member.artifact_dir,
                }
                for member in self.members
            ],
        }

    def transcripts(self) -> tuple[tuple[str, str], ...]:
        """Return labels and paths used for duplicate-source validation."""
        if self.kind == "agent":
            return ((self.name, self.path),)
        return tuple((member.name, member.path) for member in self.members)


def _resolve_agent_chat_path(name: str | None = None) -> str:
    """Return the chat path for an explicit or default resume target.

    Explicit names preserve the legacy lookup order: completed agents use
    ``done.json``'s ``response_path`` first, then any live/historical agent may
    provide ``agent_meta.json``'s ``chat_path``. An omitted name resolves to the
    most recently launched named agent, excluding ``SASE_ARTIFACTS_DIR`` so an
    agent cannot accidentally resume itself.
    """
    resolved_name = _normalize_name(name)
    if resolved_name is None:
        resolved_name = _resolve_default_agent_name()

    response_path = _resolve_done_response_path(resolved_name)
    if response_path:
        return response_path

    chat_path = _resolve_meta_chat_path(resolved_name)
    if chat_path:
        return chat_path

    raise RuntimeError(f"No agent with chat history found for: {resolved_name}")


def _resolve_agent_chat_sources(names: Sequence[str]) -> list[_ForkSource]:
    """Resolve and validate every requested parent as one atomic operation."""
    requested_names: list[str | None] = list(names) or [None]
    sources: list[_ForkSource] = []
    errors: list[str] = []

    for index, requested_name in enumerate(requested_names, start=1):
        label = requested_name or "<default>"
        try:
            resolved_name = _normalize_name(requested_name)
            if resolved_name is None:
                resolved_name = _resolve_default_agent_name()
            source = _resolve_fork_source(resolved_name)
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"parent {index} ({label}): {exc}")
        else:
            sources.append(source)

    first_source_by_path: dict[str, str] = {}
    for source in sources:
        for label, path in source.transcripts():
            canonical_path = str(Path(path).expanduser().resolve(strict=False))
            previous = first_source_by_path.get(canonical_path)
            if previous is not None:
                errors.append(
                    f"parents '{previous}' and '{label}' resolve to the "
                    f"same transcript: {path}"
                )
            else:
                first_source_by_path[canonical_path] = label

    if errors:
        raise RuntimeError("Invalid fork parents:\n- " + "\n- ".join(errors))
    return sources


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point that prints resolved source metadata as JSON."""
    parser = argparse.ArgumentParser()
    parser.add_argument("name", nargs="*")
    args = parser.parse_args(argv)
    sources = _resolve_agent_chat_sources(args.name)
    source_data = [source.to_json_data() for source in sources]
    print(
        json.dumps(
            {
                # Keep the historical single-path field as a compatibility seam.
                "path": sources[0].path,
                "sources_json": json.dumps(source_data),
            }
        )
    )
    return 0


def _normalize_name(name: str | None) -> str | None:
    if name is None:
        return None
    stripped = name.strip()
    if not stripped:
        return None
    if parse_tribe_reference(stripped) is not None:
        return stripped
    if is_agent_name_template(stripped):
        return _resolve_template_name_excluding_current_agent(stripped)
    return resolve_agent_name_template_reference(stripped)


def _resolve_template_name_excluding_current_agent(name: str) -> str:
    current_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not current_artifacts_dir:
        return resolve_agent_name_template_reference(name)

    current = Path(current_artifacts_dir).expanduser().resolve(strict=False)
    reserved = {
        agent_name
        for agent_name, owner_path in get_reserved_agent_name_map().items()
        if Path(owner_path).expanduser().resolve(strict=False) != current
    }
    return require_latest_agent_name_template(name, names=reserved)


def _resolve_default_agent_name() -> str:
    name = get_most_recent_agent_name(
        exclude_artifacts_dir=os.environ.get("SASE_ARTIFACTS_DIR")
    )
    if not name:
        raise RuntimeError("No previous named agent found for bare #fork")
    return name


def _resolve_fork_source(name: str) -> _ForkSource:
    """Resolve *name* to an agent transcript or a complete clan generation."""
    tribe = parse_tribe_reference(name)
    if tribe is not None:
        return _resolve_tribe_fork_source(name, tribe)

    clan = find_agent_clan(name)
    if clan is None:
        source = _ForkSource(
            kind="agent",
            name=name,
            path=_resolve_agent_chat_path(name),
        )
        _validate_readable_transcript(source.name, source.path)
        return source

    if not clan.is_complete:
        raise RuntimeError(f"No agent with chat history found for: {name}")

    members: list[_ForkClanMemberSource] = []
    for member in clan.members:
        path = _read_json_string_field(
            member.artifacts_dir / "done.json", "response_path"
        )
        if path is None:
            raise RuntimeError(
                f"No agent with chat history found for clan member: {member.name}"
            )
        _validate_readable_transcript(member.name, path)
        members.append(
            _ForkClanMemberSource(
                name=member.name,
                path=path,
                artifact_dir=str(member.artifacts_dir),
            )
        )

    newest_member = max(members, key=lambda member: Path(member.artifact_dir).name)
    return _ForkSource(
        kind="clan",
        name=clan.name,
        path=newest_member.path,
        generation=clan.generation,
        tribe=_resolve_clan_tribe(clan),
        members=tuple(members),
    )


def _resolve_tribe_fork_source(reference: str, tribe: str) -> _ForkSource:
    """Resolve a tribe ref to the wait side's canonical next complete entity.

    The implied wait normally makes an unresolved result unreachable. Rebuilding
    the all-project index here preserves the wait check's entity aggregation and
    earliest-launch ordering when the fork workflow starts after the barrier.
    """
    current_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not current_artifacts_dir:
        raise RuntimeError(
            f"Cannot resolve tribe fork target {reference!r}: "
            "SASE_ARTIFACTS_DIR is not set"
        )

    current = Path(current_artifacts_dir).expanduser().resolve(strict=False)
    candidate = _build_all_projects_wait_index().tribe_candidate(
        tribe,
        newer_than=current.name,
        exclude_artifact_dir=current,
    )
    if candidate is None:
        raise RuntimeError(
            f"No completed @{tribe} entity launched after {current.name}"
        )
    return _fork_source_from_tribe_candidate(candidate)


def _build_all_projects_wait_index() -> WaitDependencyIndex:
    """Build the same cross-project artifact index used by wait-check chops."""
    projects_dir = sase_projects_dir()
    index = WaitDependencyIndex.empty()
    if not projects_dir.exists():
        return index

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for artifact_dir in iter_agent_artifact_dirs(
            project_dir.name,
            "ace-run",
            projects_root=projects_dir,
        ):
            meta = read_json_dict(artifact_dir / "agent_meta.json")
            if meta is not None:
                index.add(artifact_dir, meta, project_name=project_dir.name)
    return index


def _fork_source_from_tribe_candidate(candidate: TribeCandidate) -> _ForkSource:
    """Project a selected wait candidate into the fork workflow source wire."""
    if candidate.kind == "agent":
        member = candidate.members[0]
        path = _completed_response_path(member.name, Path(member.artifact_dir))
        return _ForkSource(kind="agent", name=member.name, path=path)

    members = tuple(
        _ForkClanMemberSource(
            name=member.name,
            path=_completed_response_path(member.name, Path(member.artifact_dir)),
            artifact_dir=member.artifact_dir,
        )
        for member in sorted(candidate.members, key=lambda item: item.timestamp)
    )
    newest_member = max(members, key=lambda member: Path(member.artifact_dir).name)
    return _ForkSource(
        kind="clan",
        name=candidate.name,
        path=newest_member.path,
        generation=candidate.generation,
        tribe=candidate.tribe,
        members=members,
    )


def _completed_response_path(name: str, artifact_dir: Path) -> str:
    path = _read_json_string_field(artifact_dir / "done.json", "response_path")
    if path is None:
        raise RuntimeError(f"No agent with chat history found for: {name}")
    _validate_readable_transcript(name, path)
    return path


def _resolve_clan_tribe(clan: AgentClan) -> str | None:
    """Resolve the effective explicit tribe for one clan generation."""
    from sase.core.agent_clan_tribe import ClanTribeMemberWire, resolve_clan_tribe

    wire_members: list[ClanTribeMemberWire] = []
    has_explicit_tribe = False
    for member in clan.members:
        meta = _read_json_dict(member.artifacts_dir / "agent_meta.json")
        raw_tribe = meta.get("clan_tribe") if meta is not None else None
        tribe = raw_tribe if isinstance(raw_tribe, str) and raw_tribe else None
        has_explicit_tribe = has_explicit_tribe or tribe is not None
        wire_members.append(
            ClanTribeMemberWire(
                agent_clan=clan.name,
                agent_clan_generation=member.generation,
                clan_tribe=tribe,
                launch_timestamp=member.timestamp,
                identity=f"{member.artifacts_dir}:{member.name}",
            )
        )
    if not has_explicit_tribe:
        return None
    return resolve_clan_tribe(clan.name, clan.generation, wire_members).tribe


def _validate_readable_transcript(name: str, transcript_path: str) -> None:
    path = Path(transcript_path).expanduser()
    try:
        with open(path, encoding="utf-8"):
            pass
    except OSError as exc:
        raise OSError(
            f"Transcript for agent '{name}' is not readable: {transcript_path}"
        ) from exc


def _resolve_done_response_path(name: str) -> str | None:
    agent = resolve_resume_agent_name(name)
    if agent is None:
        return None
    return _read_json_string_field(
        Path(agent.artifacts_dir) / "done.json", "response_path"
    )


def _resolve_meta_chat_path(name: str) -> str | None:
    agent = find_named_agent(name)
    if agent is None:
        return None
    return _read_json_string_field(
        Path(agent.artifacts_dir) / "agent_meta.json", "chat_path"
    )


def _read_json_string_field(path: Path, field: str) -> str | None:
    data = _read_json_dict(path)
    if data is None:
        return None
    value = data.get(field)
    return value if isinstance(value, str) and value else None


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data: Any = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    return data if isinstance(data, dict) else None


if __name__ == "__main__":
    raise SystemExit(main())
