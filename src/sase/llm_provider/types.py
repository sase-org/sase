"""Shared types for the LLM provider abstraction layer."""

from dataclasses import dataclass, field
from typing import Any, Literal

ModelTier = Literal["large", "small"]


class LLMInvocationError(Exception):
    """Raised when an LLM provider invocation fails.

    Carries the formatted error content so callers can inspect or display it.
    """

    pass


# Mapping from old terminology to new
_MODEL_SIZE_TO_TIER: dict[str, ModelTier] = {"big": "large", "little": "small"}

# Reverse mapping for display
_MODEL_TIER_TO_LABEL: dict[ModelTier, str] = {"large": "BIG", "small": "LITTLE"}


@dataclass(frozen=True)
class InvokeResult:
    """Result from an LLM provider invocation."""

    content: str
    usage: dict[str, int] | None = None


@dataclass
class LoggingContext:
    """Context for logging prompts and responses."""

    agent_type: str = "agent"
    iteration: int | None = None
    workflow_tag: str | None = None
    artifacts_dir: str | None = None
    suppress_output: bool = False
    workflow: str | None = None
    timestamp: str | None = None
    is_home_mode: bool = False
    branch_or_workspace: str | None = None
    decision_counts: dict[str, Any] | None = field(default=None)
