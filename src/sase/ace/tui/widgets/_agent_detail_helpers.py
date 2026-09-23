"""Shared private helpers for the AgentDetail widget."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.agent.status_buckets import (
    ACTIVE_PLAN_HANDOFF_STATUSES,
    PENDING_PLAN_REVIEW_STATUSES,
)

if TYPE_CHECKING:
    from .prompt_panel import AgentPromptPanel


def agent_prompt_panel_type() -> type[AgentPromptPanel]:
    from .prompt_panel import AgentPromptPanel

    return AgentPromptPanel


_ACTIVE_STATUSES = frozenset(
    {
        "RUNNING",
        "WAITING",
        "QUEUED",
        "WAITING INPUT",
        *PENDING_PLAN_REVIEW_STATUSES,
        *ACTIVE_PLAN_HANDOFF_STATUSES,
        "QUESTION",
        "ANSWERED",
        "RETRYING",
    }
)
