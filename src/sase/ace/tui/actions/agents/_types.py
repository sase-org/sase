"""Type definitions for agent notification actions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models.agent import AgentType


@dataclass
class PlanFeedbackContext:
    """Context stored while the user writes plan feedback via PromptInputBar."""

    notification_id: str
    response_path: Path
    agent_identity: tuple[AgentType, str, str | None] | None
    plan_file: str


@dataclass
class ApprovePromptContext:
    """Context stored while the user edits the coder prompt via PromptInputBar."""

    notification: Notification
    plan_file: str
    commit_plan: bool
    run_coder: bool
    current_prompt: str
