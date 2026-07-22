"""Rendering and status helpers for the Agents-tab zoom panel modal."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text

from sase.agent.status_buckets import (
    ACTIVE_PLAN_HANDOFF_STATUSES,
    FEEDBACK_STATUS,
    PENDING_PLAN_REVIEW_STATUSES,
    PENDING_EPIC_STATUS,
    PENDING_TALE_STATUS,
    PLAN_APPROVED_STATUS,
    TALE_APPROVED_STATUS,
    WORKING_PLAN_STATUS,
    WORKING_TALE_STATUS,
)

from ..models.agent_status import STOPPED_COLOR, STOPPED_GLYPH, STOPPED_STATUS
from ..widgets.renderable_text import renderable_to_text

if TYPE_CHECKING:
    from ..models import Agent


ACTIVE_STATUSES = frozenset(
    {
        "RUNNING",
        "WAITING",
        "WAITING INPUT",
        *PENDING_PLAN_REVIEW_STATUSES,
        *ACTIVE_PLAN_HANDOFF_STATUSES,
        "QUESTION",
        "ANSWERED",
        "RETRYING",
    }
)


def agent_label(agent: Agent | None) -> str:
    if agent is None:
        return "agent missing"
    name = agent.presented_agent_name or agent.display_name
    return name[:72] + "..." if len(name) > 75 else name


def status_text(status: str) -> Text:
    style = {
        "RUNNING": "bold green",
        "WAITING": "bold yellow",
        "WAITING INPUT": "bold yellow",
        "QUESTION": "bold yellow",
        "ANSWERED": "bold #5FD7FF",
        "PLAN": "bold #FFD787",
        PENDING_TALE_STATUS: "bold #FFD787",
        PENDING_EPIC_STATUS: "bold #D787FF",
        FEEDBACK_STATUS: "bold #FF5FD7",
        PLAN_APPROVED_STATUS: "bold #FFD787",
        TALE_APPROVED_STATUS: "bold #FFD7AF",
        WORKING_PLAN_STATUS: "bold #FFAF87",
        WORKING_TALE_STATUS: "bold #FFAFAF",
        "DONE": "bold cyan",
        "FAILED": "bold red",
        "MISSING": "dim",
        STOPPED_STATUS: f"bold {STOPPED_COLOR}",
    }.get(status, "bold")
    if status == STOPPED_STATUS:
        icon = STOPPED_GLYPH
    else:
        icon = "▶" if status in ACTIVE_STATUSES else "●"
    return Text(f"{icon} {status}", style=style)


__all__ = [
    "ACTIVE_STATUSES",
    "agent_label",
    "renderable_to_text",
    "status_text",
]
