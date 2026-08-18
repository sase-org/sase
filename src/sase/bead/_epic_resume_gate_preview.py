"""Human-facing text rendered by the EpicResume gate.

Every renderer here is reconstructed byte for byte by gate validation, so all
of it is a pure function of the persisted payload: finish times and the
stalled-since instant are stored absolute values, never a live clock, and
project labels come from :func:`sase.project_display_names.project_display_name_for`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sase.bead._task_gate_preview import bounded_gate_title
from sase.project_display_names import project_display_name_for

_FAILED_COLUMNS = ("Agent", "Phase bead", "Finished")
_WAITING_COLUMNS = ("Agent", "Phase bead")


def parse_epic_resume_instant(value: str) -> datetime:
    """Parse one payload instant as a timezone-aware datetime.

    Uses the same ``Z`` → ``+00:00`` convention as :mod:`sase.bead.model`.
    A naive value is rejected so a preview cannot silently depend on the
    host timezone.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"epic resume instant must be timezone-aware: {value!r}")
    return parsed


def _epic_resume_project_label(project: str) -> str:
    """Return the user-facing project name for one payload project key."""
    return project_display_name_for(project)


def epic_resume_presentation_title(epic_id: str) -> str:
    """Return the bounded notification headline for one stalled epic."""
    return bounded_gate_title(epic_id, "Resume stalled epic")


def render_epic_resume_preview(payload: Any) -> str:
    """Render the reviewed Markdown detail shown by ACE and mobile clients.

    The body names the epic, lists each failed agent with its phase bead and
    finish time, states how many phases are still waiting, and quotes the
    exact argv Resume epic will run. Nothing agent-authored reaches it.
    """
    epic_id = str(_payload_attr(payload, "epic_id"))
    epic_title = str(_payload_attr(payload, "epic_title")).strip()
    project = _epic_resume_project_label(str(_payload_attr(payload, "project")))
    generation = str(_payload_attr(payload, "clan_generation"))
    stalled_since = str(_payload_attr(payload, "stalled_since"))
    remaining = int(_payload_attr(payload, "remaining_phase_count"))
    resume_argv = [str(part) for part in _payload_attr(payload, "resume_argv")]
    failed_rows = [
        _failed_row(member) for member in _payload_attr(payload, "failed_members")
    ]
    waiting_members: Sequence[Any] = _payload_attr(payload, "waiting_members")
    epic_line = f"{epic_id} — {epic_title}" if epic_title else epic_id
    phase_noun = "phase" if remaining == 1 else "phases"
    command = " ".join(resume_argv)
    sections = [
        f"# Resume stalled epic {epic_id}",
        "",
        f"**Epic:** {epic_line}",
        f"**Project:** {_markdown_cell(project)}",
        f"**Clan generation:** `{_markdown_code(generation)}`",
        f"**Stalled since:** `{_markdown_code(stalled_since)}`",
        f"**Phases still waiting:** {remaining} {phase_noun}",
        "",
        "A failed phase agent stalled this epic. No clan member is live, so "
        "later phases cannot advance until the epic is relaunched.",
        "",
        "## Failed agents",
        "",
        _markdown_table(_FAILED_COLUMNS, failed_rows),
    ]
    if waiting_members:
        waiting_rows = [_waiting_row(member) for member in waiting_members]
        sections.extend(
            [
                "",
                "## Waiting phases",
                "",
                _markdown_table(_WAITING_COLUMNS, waiting_rows),
            ]
        )
    sections.extend(
        [
            "",
            "## Resume command",
            "",
            "Answering **Resume epic** runs this exact command as a detached "
            "leased proc:",
            "",
            f"`{_markdown_code(command)}`",
            "",
            "Dismissing this notification declines the stall until a new "
            "failure occurs.",
            "",
        ]
    )
    return "\n".join(sections)


def epic_resume_presentation_note(payload: Any) -> str:
    """Return the one-line notification note for one epic-resume gate."""
    epic_id = str(_payload_attr(payload, "epic_id"))
    title = str(_payload_attr(payload, "epic_title")).strip()
    failed = [
        str(_member_attr(member, "agent_name"))
        for member in _payload_attr(payload, "failed_members")
    ]
    noun = "agent" if len(failed) == 1 else "agents"
    names = ", ".join(failed)
    head = f"{epic_id} — {title}" if title else epic_id
    return f"{head} · {len(failed)} failed {noun}: {names}"


def _failed_row(member: Any) -> tuple[str, ...]:
    finished = _member_attr(member, "finished_at")
    return (
        str(_member_attr(member, "agent_name")),
        str(_member_attr(member, "bead_id")),
        "" if finished is None else str(finished),
    )


def _waiting_row(member: Any) -> tuple[str, ...]:
    return (
        str(_member_attr(member, "agent_name")),
        str(_member_attr(member, "bead_id")),
    )


def _payload_attr(payload: Any, name: str) -> Any:
    if isinstance(payload, Mapping):
        return payload[name]
    return getattr(payload, name)


def _member_attr(member: Any, name: str) -> Any:
    if isinstance(member, Mapping):
        return member[name]
    return getattr(member, name)


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    header = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| " + " | ".join(_markdown_cell(cell) for cell in row) + " |" for row in rows
    ]
    return "\n".join([header, divider, *body])


def _markdown_cell(value: str) -> str:
    return value.replace("\n", " ").replace("|", "\\|")


def _markdown_code(value: str) -> str:
    return value.replace("`", "\\`")


__all__ = [
    "epic_resume_presentation_note",
    "epic_resume_presentation_title",
    "parse_epic_resume_instant",
    "render_epic_resume_preview",
]
