"""Failure payload assembly for named-agent fork sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.agent.names import AgentFamilyMember
from sase.history.chat_storage import find_chat_by_timestamp
from sase.scripts._agent_chat_from_name_common import (
    format_finished_at,
    json_string,
    read_json_string_field,
    read_sanitized_launch_prompt,
    validate_readable_transcript,
)
from sase.scripts._agent_chat_from_name_models import (
    ForkFailure,
    ForkFamilyMemberSource,
    ForkSource,
)


def failed_agent_fork_source(
    name: str,
    artifact_dir: Path,
    done: dict[str, Any],
    outcome: str,
) -> ForkSource:
    transcript_path = _resolve_failed_agent_transcript(name, artifact_dir, done)
    transcript_available = bool(transcript_path)
    failure = ForkFailure(
        outcome=outcome,
        error=json_string(done, "error"),
        traceback=json_string(done, "traceback"),
        ended_at=format_finished_at(done.get("finished_at")),
        transcript_available=transcript_available,
        launch_prompt=(
            None if transcript_available else read_sanitized_launch_prompt(artifact_dir)
        ),
    )
    return ForkSource(
        kind="agent",
        name=name,
        path=transcript_path,
        failure=failure,
    )


def failed_agent_family_member_shell(
    member: AgentFamilyMember,
    done: dict[str, Any],
    outcome: str,
) -> ForkFamilyMemberSource:
    transcript_path = _resolve_failed_agent_transcript(
        member.name, member.artifacts_dir, done
    )
    transcript_available = bool(transcript_path)
    failure = ForkFailure(
        outcome=outcome,
        error=json_string(done, "error"),
        traceback=json_string(done, "traceback"),
        ended_at=format_finished_at(done.get("finished_at")),
        transcript_available=transcript_available,
        launch_prompt=(
            None
            if transcript_available
            else read_sanitized_launch_prompt(member.artifacts_dir)
        ),
    )
    return ForkFamilyMemberSource(
        name=member.name,
        artifact_dir=str(member.artifacts_dir),
        outcome=outcome,
        kind="agent",
        path=transcript_path,
        failure=failure,
    )


def _resolve_failed_agent_transcript(
    name: str,
    artifact_dir: Path,
    done: dict[str, Any],
) -> str:
    candidates = [
        json_string(done, "response_path"),
        read_json_string_field(artifact_dir / "agent_meta.json", "chat_path"),
        find_chat_by_timestamp(artifact_dir.name),
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            validate_readable_transcript(name, candidate)
        except OSError:
            continue
        return candidate
    return ""
