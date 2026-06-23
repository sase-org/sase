"""Shared types for the LLM provider abstraction layer."""

from dataclasses import dataclass, field
from typing import Any, Literal

ModelTier = Literal["large", "small"]
ModelRole = Literal["primary", "worker"]


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


@dataclass(frozen=True)
class LLMInvocationOptions:
    """Per-invocation options resolved from prompt directives plus config.

    Threaded from :func:`invoke_agent` through the provider chain so a resolved
    reasoning-effort level becomes the right per-run CLI args. ``explicit``
    records whether the effort was requested explicitly (``%effort``/
    ``@effort``) or merely inherited from ``llm_provider.default_effort``: the
    provider adapter raises on an unsupported *explicit* effort but silently
    skips an unsupported *default* one, so a global default never breaks a run.

    The field spells the internal name ``reasoning_effort`` to match
    ``PromptDirectives`` and the persisted ``agent_meta.json`` field; only the
    public ``%effort`` directive/config surface uses the shorter ``effort``.
    """

    reasoning_effort: str | None = None
    explicit: bool = False


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
    metadata_model: str | None = None
    metadata_llm_provider: str | None = None
    metadata_agent: str | None = None
