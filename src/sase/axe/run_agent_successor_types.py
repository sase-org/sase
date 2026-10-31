"""Result types for the in-process agent-session-successor engine."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

STAGED_SUCCESSOR_ORIGIN_DIR_ENV = "SASE_STAGED_SUCCESSOR_ORIGIN_DIR"
STAGED_SUCCESSOR_ID_ENV = "SASE_STAGED_SUCCESSOR_ID"


@dataclass(frozen=True)
class FollowupModel:
    """The follow-up agent's model directive prefix and metadata.

    ``model_prefix`` is prepended to the generated follow-up prompt (for
    example, ``"%model:codex/gpt-6.1-sol\\n"``). ``meta`` is the
    ``(provider_or_none, model)`` written to the follow-up's
    ``agent_meta.json``. It is ``None`` when the inherited planner metadata is
    already correct and does not need to be rewritten.
    """

    model_prefix: str
    meta: tuple[str | None, str] | None = None
    model_alias: str | None = None
    model_alias_trail: tuple[str, ...] = ()
    model_alias_origin: str | None = None


@dataclass(frozen=True)
class SuccessorRequest:
    """Inputs for :func:`continue_as_successor`.

    Exactly one of ``suffix`` or ``suffix_template`` must be set. An
    ``@``-bearing template is allocated when the agent is named and rendered
    with ``fallback_token`` when it is not.
    """

    base_meta: dict[str, Any]
    prompt: str
    suffix: str | None = None
    suffix_template: str | None = None
    extra_reserved_suffixes: tuple[str, ...] = ()
    agent_session_role: str | None = None
    relationships: dict[str, Any] = field(default_factory=dict)
    prompt_artifact_label: str = "Full follow-up prompt"
    model: FollowupModel | None = None
    promote_role_suffix: str | None = None
    fallback_token: str = "0"
    reserved_timestamp: str | None = None
    before_state_change: Callable[[str, str], None] | None = None
    before_create: Callable[[str, str], None] | None = None

    def __post_init__(self) -> None:
        if (self.suffix is None) == (self.suffix_template is None):
            raise ValueError("exactly one of suffix or suffix_template must be set")


@dataclass(frozen=True)
class SuccessorDeliveryResult:
    """Observed result of detached successor delivery."""

    state: str
    agent_name: str
    artifacts_dir: str
    pid: int | None = None
    reason: str | None = None


__all__ = [
    "FollowupModel",
    "STAGED_SUCCESSOR_ID_ENV",
    "STAGED_SUCCESSOR_ORIGIN_DIR_ENV",
    "SuccessorDeliveryResult",
    "SuccessorRequest",
]
