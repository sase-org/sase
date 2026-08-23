"""Core agent identity value types."""

from __future__ import annotations

from enum import Enum


class AgentType(Enum):
    """Types of agents that can be tracked."""

    RUNNING = "run"  # Manual sase run commands (RUNNING field)
    WORKFLOW = "workflow"  # Multi-step YAML workflows
    PROC_SHELL = "proc-shell"  # Stand-alone durable proc shell projection


AgentIdentity = tuple[AgentType, str, str | None]


__all__ = ["AgentIdentity", "AgentType"]
