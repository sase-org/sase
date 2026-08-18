"""Structured payload parsing for EpicResume gate validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from sase.bead._epic_resume_gate_preview import parse_epic_resume_instant
from sase.notification_gates.models import GateError

_EPIC_RESUME_PAYLOAD_FIELDS = frozenset(
    {
        "project",
        "epic_id",
        "epic_title",
        "clan_generation",
        "failed_members",
        "waiting_members",
        "remaining_phase_count",
        "resume_argv",
        "stalled_since",
    }
)
_EPIC_RESUME_MEMBER_FIELDS = frozenset({"agent_name", "bead_id", "finished_at"})


@dataclass(frozen=True)
class _EpicResumeMember:
    """One clan member projected into an EpicResume payload."""

    agent_name: str
    bead_id: str
    finished_at: str | None


@dataclass(frozen=True)
class EpicResumePayload:
    """The validated, structurally typed view of an epic-resume gate payload."""

    project: str
    epic_id: str
    epic_title: str
    clan_generation: str
    failed_members: tuple[_EpicResumeMember, ...]
    waiting_members: tuple[_EpicResumeMember, ...]
    remaining_phase_count: int
    resume_argv: tuple[str, ...]
    stalled_since: str


def parse_epic_resume_payload(payload: Mapping[str, Any]) -> EpicResumePayload:
    """Validate *payload* against the structured EpicResume contract."""
    from sase.bead.epic_resume_launch import build_epic_resume_argv
    from sase.core.paths import is_valid_sase_project_name

    if set(payload) != _EPIC_RESUME_PAYLOAD_FIELDS:
        raise GateError(
            "invalid_epic_resume_payload",
            "payload",
            "epic resume payload does not match the structured presentation contract",
        )
    project = payload.get("project")
    if not isinstance(project, str) or not is_valid_sase_project_name(project):
        raise GateError(
            "invalid_epic_resume_payload",
            "payload.project",
            "epic resume payload requires a canonical SASE project key",
        )
    epic_id = payload.get("epic_id")
    if not isinstance(epic_id, str) or not epic_id.strip():
        raise GateError(
            "invalid_epic_resume_payload",
            "payload.epic_id",
            "epic resume payload requires epic_id",
        )
    epic_title = payload.get("epic_title")
    if not isinstance(epic_title, str):
        raise GateError(
            "invalid_epic_resume_payload",
            "payload.epic_title",
            "epic resume payload epic_title must be a string",
        )
    clan_generation = payload.get("clan_generation")
    if not isinstance(clan_generation, str) or not clan_generation.strip():
        raise GateError(
            "invalid_epic_resume_payload",
            "payload.clan_generation",
            "epic resume payload requires clan_generation",
        )
    stalled_since = _require_aware_instant(
        payload.get("stalled_since"), field="stalled_since"
    )
    remaining_phase_count = _require_int(
        payload.get("remaining_phase_count"),
        field="remaining_phase_count",
        minimum=0,
    )
    failed_members = _parse_members(
        payload.get("failed_members"),
        field="failed_members",
        require_finished=True,
        allow_empty=False,
    )
    waiting_members = _parse_members(
        payload.get("waiting_members"),
        field="waiting_members",
        require_finished=False,
        allow_empty=True,
    )
    resume_argv = payload.get("resume_argv")
    if not isinstance(resume_argv, list) or any(
        not isinstance(part, str) for part in resume_argv
    ):
        raise GateError(
            "invalid_epic_resume_payload",
            "payload.resume_argv",
            "epic resume payload resume_argv must be a string list",
        )
    expected_argv = build_epic_resume_argv(epic_id)
    if resume_argv != expected_argv:
        raise GateError(
            "invalid_epic_resume_payload",
            "payload.resume_argv",
            "epic resume payload resume_argv does not match the registered adapter",
        )
    return EpicResumePayload(
        project=project,
        epic_id=epic_id,
        epic_title=epic_title,
        clan_generation=clan_generation,
        failed_members=failed_members,
        waiting_members=waiting_members,
        remaining_phase_count=remaining_phase_count,
        resume_argv=tuple(cast(list[str], resume_argv)),
        stalled_since=stalled_since,
    )


def _parse_members(
    raw_members: object,
    *,
    field: str,
    require_finished: bool,
    allow_empty: bool,
) -> tuple[_EpicResumeMember, ...]:
    if not isinstance(raw_members, list):
        raise GateError(
            "invalid_epic_resume_payload",
            f"payload.{field}",
            f"epic resume payload {field} must be an array",
        )
    if not raw_members and not allow_empty:
        raise GateError(
            "invalid_epic_resume_payload",
            f"payload.{field}",
            f"epic resume payload {field} must not be empty",
        )
    members: list[_EpicResumeMember] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_member in enumerate(raw_members):
        target = f"payload.{field}[{index}]"
        if not isinstance(raw_member, Mapping) or set(raw_member) != (
            _EPIC_RESUME_MEMBER_FIELDS
        ):
            raise GateError(
                "invalid_epic_resume_payload",
                target,
                "epic resume member does not match the structured presentation contract",
            )
        agent_name = raw_member.get("agent_name")
        if not isinstance(agent_name, str) or not agent_name.strip():
            raise GateError(
                "invalid_epic_resume_payload",
                f"{target}.agent_name",
                "epic resume payload requires agent_name",
            )
        bead_id = raw_member.get("bead_id")
        if not isinstance(bead_id, str) or not bead_id.strip():
            raise GateError(
                "invalid_epic_resume_payload",
                f"{target}.bead_id",
                "epic resume payload requires bead_id",
            )
        identity = (agent_name, bead_id)
        if identity in seen:
            raise GateError(
                "invalid_epic_resume_payload",
                target,
                "epic resume payload has a duplicate (agent_name, bead_id)",
            )
        seen.add(identity)
        finished_at = raw_member.get("finished_at")
        if finished_at is None:
            if require_finished:
                raise GateError(
                    "invalid_epic_resume_payload",
                    f"{target}.finished_at",
                    "epic resume failed member requires finished_at",
                )
        else:
            _require_aware_instant(finished_at, field=f"{field}[{index}].finished_at")
        members.append(
            _EpicResumeMember(
                agent_name=agent_name,
                bead_id=bead_id,
                finished_at=cast("str | None", finished_at),
            )
        )
    return tuple(members)


def _require_aware_instant(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateError(
            "invalid_epic_resume_payload",
            f"payload.{field}",
            f"epic resume payload requires {field}",
        )
    try:
        parse_epic_resume_instant(value)
    except ValueError as exc:
        raise GateError(
            "invalid_epic_resume_payload",
            f"payload.{field}",
            f"epic resume payload {field} must be a timezone-aware ISO-8601 instant",
        ) from exc
    return value


def _require_int(value: object, *, field: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise GateError(
            "invalid_epic_resume_payload",
            f"payload.{field}",
            f"epic resume payload {field} must be an integer >= {minimum}",
        )
    return value


__all__ = [
    "EpicResumePayload",
    "parse_epic_resume_payload",
]
