"""Core agent identity value types."""

from __future__ import annotations

from enum import Enum


class AgentType(Enum):
    """Types of agents that can be tracked."""

    RUNNING = "run"  # Manual sase run commands (RUNNING field)
    WORKFLOW = "workflow"  # Multi-step YAML workflows
    NAMED_PROC = "named-proc"  # Stand-alone durable named proc projection

    @classmethod
    def _missing_(cls, value: object) -> AgentType | None:
        # legacy sase-shell spelling: pre-rename rows carry ``proc-shell``.
        if value == "proc-shell":
            return cls.NAMED_PROC
        return None


AgentIdentity = tuple[AgentType, str, str | None]


__all__ = ["AgentIdentity", "AgentType"]
