"""Type definitions for agent notification actions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models.agent import AgentType


@dataclass
class PlanFeedbackContext:
    """Context stored while the user writes plan feedback via PromptInputBar."""

    notification_id: str
    response_path: Path
    agent_identity: tuple[AgentType, str, str | None] | None
    plan_file: str
