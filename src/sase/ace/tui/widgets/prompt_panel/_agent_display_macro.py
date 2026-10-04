"""Detached macro attachment and cheap-path memo support."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, cast

from rich.text import Text

from ...models.agent import Agent, AgentType
from ._agent_display_header_renderable import AgentHeader, AgentHeaderRenderable

_RAW_PROMPT_MEMO_LIMIT = 128


def raw_prompt_hints_enabled(panel: object) -> bool:
    """Return whether a detached raw_prompt may carry hint markers."""
    if not bool(getattr(panel, "detaches_raw_prompt", False)):
        return True
    return bool(getattr(panel, "identity_header_hints_enabled", True))


def attach_raw_prompt_to_identity(
    panel: object,
    document: AgentHeader,
    raw_prompt: Text,
) -> bool:
    """Attach ``raw_prompt`` to a detached identity, returning whether it moved."""
    if not bool(getattr(panel, "detaches_raw_prompt", False)):
        return False
    if not isinstance(document, AgentHeaderRenderable):
        return False
    identity = document.identity_header
    if identity is None:
        return False
    document.with_identity_header(identity.with_raw_prompt(raw_prompt))
    return True


def _agent_may_show_raw_prompt(
    agent: Agent,
    *,
    attempt_pinned: bool = False,
) -> bool:
    """Return whether a regular full paint could render an agent raw_prompt."""
    if attempt_pinned or agent.is_clan_container:
        return False
    if agent.is_named_proc or agent.is_monitor or agent.is_gate:
        return False
    if agent.is_workflow_child and agent.step_type in {"bash", "python", "parallel"}:
        return False
    return not (
        agent.agent_type == AgentType.WORKFLOW
        and not agent.is_workflow_child
        and not agent.appears_as_agent
    )


def _raw_prompt_memo(widget: object) -> OrderedDict[object, Text | None]:
    memo = getattr(widget, "_agent_raw_prompt_memo", None)
    if memo is None:
        memo = OrderedDict()
        cast(Any, widget)._agent_raw_prompt_memo = memo
    return memo


def memoize_raw_prompt(panel: object, agent: Agent, raw_prompt: Text | None) -> None:
    """Record one full-paint raw_prompt in the bounded panel-local LRU."""
    if not bool(getattr(panel, "detaches_raw_prompt", False)):
        return
    memo = _raw_prompt_memo(panel)
    key = agent.identity
    if key in memo:
        memo.pop(key)
    memo[key] = raw_prompt.copy() if raw_prompt is not None else None
    while len(memo) > _RAW_PROMPT_MEMO_LIMIT:
        memo.popitem(last=False)


def attach_memoized_raw_prompt(
    panel: object,
    agent: Agent,
    document: AgentHeader,
    *,
    attempt_pinned: bool,
) -> None:
    """Use a memo hit, or hold space pending the debounced full paint."""
    if not bool(getattr(panel, "detaches_raw_prompt", False)) or attempt_pinned:
        return
    if not isinstance(document, AgentHeaderRenderable):
        return
    identity = document.identity_header
    if identity is None:
        return
    memo = _raw_prompt_memo(panel)
    key = agent.identity
    if key in memo:
        raw_prompt = memo.pop(key)
        memo[key] = raw_prompt
        if raw_prompt is not None:
            document.with_identity_header(identity.with_raw_prompt(raw_prompt))
        return
    if _agent_may_show_raw_prompt(agent):
        document.with_identity_header(identity.with_raw_prompt_pending())


__all__ = [
    "attach_memoized_raw_prompt",
    "attach_raw_prompt_to_identity",
    "memoize_raw_prompt",
    "raw_prompt_hints_enabled",
]
