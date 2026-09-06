"""Shared helpers for named-agent chat source resolution."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.agent.names import (
    AgentClan,
    AgentFamilyMember,
    find_agent_family,
    find_named_agent,
    get_most_recent_agent_name,
    get_reserved_agent_name_map,
    is_agent_name_template,
    require_latest_agent_name_template,
    resolve_agent_name_template_reference,
    resolve_resume_agent_name,
)
from sase.core.agent_tribe import parse_tribe_reference
from sase.core.agent_identity_facade import (
    AgentFamilyNameKind,
    parse_agent_family_name,
)
from sase.core.dismissed_agent_completion import (
    ArchivedAgentCompletion,
    archived_response_path,
)
from sase.core.time import format_local
from sase.history.chat_resume import sanitize_resume_prompt
from sase.plan_chain import agent_family_base

_MAX_LAUNCH_PROMPT_CHARS = 2000


def normalize_name(name: str | None) -> str | None:
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


def resolve_default_agent_name() -> str:
    name = get_most_recent_agent_name(
        exclude_artifacts_dir=os.environ.get("SASE_ARTIFACTS_DIR")
    )
    if not name:
        raise RuntimeError("No previous named agent found for bare #fork")
    return name


def completed_response_path(
    name: str,
    artifact_dir: Path,
    *,
    archived_completion: ArchivedAgentCompletion | None = None,
    clan_member: bool = False,
) -> str:
    path = read_json_string_field(artifact_dir / "done.json", "response_path")
    if path is None and archived_completion is not None:
        path = archived_response_path(archived_completion)
    if path is None:
        if clan_member:
            raise RuntimeError(
                f"No agent with chat history found for clan member: {name}"
            )
        raise RuntimeError(f"No agent with chat history found for: {name}")
    validate_readable_transcript(name, path)
    return path


def resolve_clan_tribe(clan: AgentClan) -> str | None:
    """Resolve the effective explicit tribe for one clan generation."""
    from sase.core.agent_clan_tribe import (
        ClanTribeMemberWire,
        resolve_clan_tribe as resolve_core_clan_tribe,
    )

    wire_members: list[ClanTribeMemberWire] = []
    has_explicit_tribe = False
    for member in clan.members:
        meta = read_json_dict(member.artifacts_dir / "agent_meta.json")
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
    return resolve_core_clan_tribe(clan.name, clan.generation, wire_members).tribe


def validate_readable_transcript(name: str, transcript_path: str) -> None:
    path = Path(transcript_path).expanduser()
    try:
        with open(path, encoding="utf-8"):
            pass
    except OSError as exc:
        raise OSError(
            f"Transcript for agent '{name}' is not readable: {transcript_path}"
        ) from exc


def find_family_member(name: str) -> AgentFamilyMember | None:
    """Return the exact member represented by a recognized family-child name."""
    base_name = _canonical_family_member_base(name)
    if base_name is None:
        base_name = agent_family_base(name, include_legacy_dash=True)
        if base_name is None or find_agent_family(name) is not None:
            return None
    family = find_agent_family(base_name)
    if family is None:
        return None
    return next((member for member in family.members if member.name == name), None)


def _canonical_family_member_base(name: str) -> str | None:
    try:
        parsed = parse_agent_family_name(name)
    except (RuntimeError, ValueError):
        return None
    if parsed.kind is not AgentFamilyNameKind.MEMBER:
        return None
    return parsed.family_name


def resolve_done_response_path(name: str) -> str | None:
    agent = resolve_resume_agent_name(name)
    if agent is None:
        return None
    return read_json_string_field(
        Path(agent.artifacts_dir) / "done.json", "response_path"
    )


def resolve_meta_chat_path(name: str) -> str | None:
    agent = find_named_agent(name)
    if agent is None:
        return None
    return read_json_string_field(
        Path(agent.artifacts_dir) / "agent_meta.json", "chat_path"
    )


def read_json_string_field(path: Path, field: str) -> str | None:
    data = read_json_dict(path)
    if data is None:
        return None
    return json_string(data, field)


def json_string(data: dict[str, Any], field: str) -> str | None:
    value = data.get(field)
    return value if isinstance(value, str) and value else None


def read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data: Any = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    return data if isinstance(data, dict) else None


def format_finished_at(value: object) -> str | None:
    if value is not None and not isinstance(value, str | int | float | datetime):
        return None
    rendered = format_local(
        value,
        "%Y-%m-%d %H:%M:%S %Z",
        default="",
    )
    return rendered or None


def read_sanitized_launch_prompt(artifact_dir: Path) -> str | None:
    try:
        prompt = (artifact_dir / "raw_xprompt.md").read_text(encoding="utf-8")
    except OSError:
        return None
    sanitized = sanitize_resume_prompt(prompt)
    if not sanitized:
        return None
    if len(sanitized) <= _MAX_LAUNCH_PROMPT_CHARS:
        return sanitized
    return sanitized[:_MAX_LAUNCH_PROMPT_CHARS].rstrip() + "\n… (truncated)"
