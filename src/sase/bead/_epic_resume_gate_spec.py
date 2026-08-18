"""The request shape and option command of the EpicResume gate.

Everything here defines what an EpicResume gate *is*: its constants, the one
request spec the adapter accepts, the option command wrapper, and the result
schema the resume option must emit. Gate validation rebuilds these from the
persisted payload and compares, so each helper must stay a pure function of
its arguments.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from sase.bead._epic_resume_gate_preview import (
    epic_resume_presentation_note,
    epic_resume_presentation_title,
    render_epic_resume_preview,
)
from sase.bead.epic_resume_launch import build_epic_resume_argv
from sase.notification_gates.entrypoints import gate_command_entrypoint

EpicResumeAction = Literal["resume"]

EPIC_RESUME_KIND = "epic_resume"
EPIC_RESUME_CONTINUATION_MODE = "epic_resume"
EPIC_RESUME_QUERY = "resume"
EPIC_RESUME_RESUME_OPTION_ID: EpicResumeAction = "resume"
EPIC_RESUME_OPTION_IDS: tuple[EpicResumeAction, ...] = (EPIC_RESUME_RESUME_OPTION_ID,)
EPIC_RESUME_PRIMARY_BRANCH = (EPIC_RESUME_RESUME_OPTION_ID,)
EPIC_RESUME_PREVIEW_PATH = "epic.md"
EPIC_RESUME_COMMAND_PATHS: dict[EpicResumeAction, str] = {
    EPIC_RESUME_RESUME_OPTION_ID: "commands/resume",
}


def build_epic_resume_gate_spec(
    *,
    request_id: str,
    project: str,
    epic_id: str,
    epic_title: str,
    clan_generation: int | str,
    failed_members: Sequence[Any],
    waiting_members: Sequence[Any] = (),
    remaining_phase_count: int,
    stalled_since: str,
    producer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the only request shape accepted by the EpicResume adapter."""
    resume_argv = build_epic_resume_argv(epic_id)
    failed = [_member_payload(member) for member in failed_members]
    waiting = [_member_payload(member) for member in waiting_members]
    generation = _clan_generation_value(clan_generation)
    payload = {
        "project": project,
        "epic_id": epic_id,
        "epic_title": epic_title,
        "clan_generation": generation,
        "failed_members": failed,
        "waiting_members": waiting,
        "remaining_phase_count": remaining_phase_count,
        "resume_argv": list(resume_argv),
        "stalled_since": stalled_since,
    }
    payload_view = _PayloadView(
        project=project,
        epic_id=epic_id,
        epic_title=epic_title,
        clan_generation=generation,
        failed_members=failed,
        waiting_members=waiting,
        remaining_phase_count=remaining_phase_count,
        resume_argv=list(resume_argv),
        stalled_since=stalled_since,
    )
    return {
        "schema_version": 3,
        "kind": EPIC_RESUME_KIND,
        "request_id": request_id,
        "producer": dict(producer or {}),
        "continuation_mode": EPIC_RESUME_CONTINUATION_MODE,
        "payload": payload,
        "presentation": {
            "sender": "bead",
            "icon": "🔁",
            "title": epic_resume_presentation_title(epic_id),
            "notes": [epic_resume_presentation_note(payload_view)],
            "tags": ["bead", "epic", "resume"],
            "panel": "beads",
            "panel_icon": "◈",
            "files": [EPIC_RESUME_PREVIEW_PATH],
            "preview": EPIC_RESUME_PREVIEW_PATH,
        },
        "query": EPIC_RESUME_QUERY,
        "primary_branch": list(EPIC_RESUME_PRIMARY_BRANCH),
        "options": [epic_resume_option_spec()],
        "resources": [
            {
                "path": EPIC_RESUME_COMMAND_PATHS[EPIC_RESUME_RESUME_OPTION_ID],
                "role": "command",
                "content": epic_resume_gate_command_script(),
            },
            {
                "path": EPIC_RESUME_PREVIEW_PATH,
                "role": "preview",
                "content": render_epic_resume_preview(payload_view),
            },
        ],
        "auto": False,
    }


def epic_resume_option_spec() -> dict[str, Any]:
    """Return the only spec the Resume epic option is accepted with.

    Shared with kind validation, which rebuilds the option from this helper
    rather than restating its shape, so the side-effect-free command contract
    cannot drift between what the gate is created with and what is accepted.
    """
    return {
        "id": EPIC_RESUME_RESUME_OPTION_ID,
        "label": "Resume epic",
        "icon": "▶️",
        "command": {"argv": [EPIC_RESUME_COMMAND_PATHS[EPIC_RESUME_RESUME_OPTION_ID]]},
        "result_schema": _epic_resume_result_schema(),
        "feedback": "optional",
    }


def _epic_resume_result_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["action"],
        "properties": {"action": {"const": EPIC_RESUME_RESUME_OPTION_ID}},
        "additionalProperties": False,
    }


def epic_resume_gate_command_script() -> str:
    """Return the only command wrapper accepted by the EpicResume adapter.

    The wrapper imports from :mod:`sase.bead.epic_resume_gate` because the
    script text is persisted into every gate bundle and revalidated byte for
    byte; the facade keeps that path stable no matter where the entrypoint
    lives.
    """
    return (
        f"#!{sys.executable}\n"
        "from sase.bead.epic_resume_gate import "
        "execute_epic_resume_gate_command\n"
        "raise SystemExit(execute_epic_resume_gate_command())\n"
    )


@gate_command_entrypoint
def execute_epic_resume_gate_command() -> int:
    """Validate command input and emit one typed side-effect-free result."""
    try:
        raw_input = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"invalid command input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(raw_input, dict):
        print("epic resume command input must be an object", file=sys.stderr)
        return 2
    if raw_input:
        print("epic resume command input must be empty", file=sys.stderr)
        return 2
    print(json.dumps({"action": EPIC_RESUME_RESUME_OPTION_ID}, sort_keys=True))
    return 0


def _member_payload(member: Any) -> dict[str, Any]:
    return {
        "agent_name": _member_attr(member, "agent_name"),
        "bead_id": _member_attr(member, "bead_id"),
        "finished_at": _member_attr(member, "finished_at"),
    }


def _member_attr(member: Any, name: str) -> Any:
    if isinstance(member, Mapping):
        return member[name]
    return getattr(member, name)


def _clan_generation_value(value: int | str) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    return value


class _PayloadView:
    """Duck-typed payload used while building a spec from caller arguments."""

    __slots__ = (
        "clan_generation",
        "epic_id",
        "epic_title",
        "failed_members",
        "project",
        "remaining_phase_count",
        "resume_argv",
        "stalled_since",
        "waiting_members",
    )

    def __init__(
        self,
        *,
        project: str,
        epic_id: str,
        epic_title: str,
        clan_generation: str,
        failed_members: list[dict[str, Any]],
        waiting_members: list[dict[str, Any]],
        remaining_phase_count: int,
        resume_argv: list[str],
        stalled_since: str,
    ) -> None:
        self.project = project
        self.epic_id = epic_id
        self.epic_title = epic_title
        self.clan_generation = clan_generation
        self.failed_members = failed_members
        self.waiting_members = waiting_members
        self.remaining_phase_count = remaining_phase_count
        self.resume_argv = resume_argv
        self.stalled_since = stalled_since
