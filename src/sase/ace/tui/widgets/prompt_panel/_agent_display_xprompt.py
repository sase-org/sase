"""Detached xprompt attachment and cheap-path memo support."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, cast

from rich.text import Text

from ...models.agent import Agent, AgentType
from ._agent_display_header_renderable import AgentHeader, AgentHeaderRenderable

_XPROMPT_MEMO_LIMIT = 128


def attach_xprompt_to_identity(
    panel: object,
    document: AgentHeader,
    xprompt: Text,
    *,
    has_hints: bool = False,
) -> bool:
    """Attach ``xprompt`` to a detached identity, returning whether it moved."""
    if not bool(getattr(panel, "detaches_xprompt", False)):
        return False
    if not isinstance(document, AgentHeaderRenderable):
        return False
    identity = document.identity_header
    if identity is None:
        return False
    document.with_identity_header(identity.with_xprompt(xprompt, has_hints=has_hints))
    return True


def _agent_may_show_xprompt(
    agent: Agent,
    *,
    attempt_pinned: bool = False,
) -> bool:
    """Return whether a regular full paint could render an agent xprompt."""
    if attempt_pinned or agent.is_clan_container:
        return False
    if agent.is_proc_shell or agent.is_monitor or agent.is_gate:
        return False
    if agent.is_workflow_child and agent.step_type in {"bash", "python", "parallel"}:
        return False
    return not (
        agent.agent_type == AgentType.WORKFLOW
        and not agent.is_workflow_child
        and not agent.appears_as_agent
    )


def _xprompt_memo(widget: object) -> OrderedDict[object, Text | None]:
    memo = getattr(widget, "_agent_xprompt_memo", None)
    if memo is None:
        memo = OrderedDict()
        cast(Any, widget)._agent_xprompt_memo = memo
    return memo


def memoize_xprompt(panel: object, agent: Agent, xprompt: Text | None) -> None:
    """Record one full-paint xprompt in the bounded panel-local LRU."""
    if not bool(getattr(panel, "detaches_xprompt", False)):
        return
    memo = _xprompt_memo(panel)
    key = agent.identity
    if key in memo:
        memo.pop(key)
    memo[key] = xprompt.copy() if xprompt is not None else None
    while len(memo) > _XPROMPT_MEMO_LIMIT:
        memo.popitem(last=False)


def attach_memoized_xprompt(
    panel: object,
    agent: Agent,
    document: AgentHeader,
    *,
    attempt_pinned: bool,
) -> None:
    """Use a memo hit, or hold space pending the debounced full paint."""
    if not bool(getattr(panel, "detaches_xprompt", False)) or attempt_pinned:
        return
    if not isinstance(document, AgentHeaderRenderable):
        return
    identity = document.identity_header
    if identity is None:
        return
    memo = _xprompt_memo(panel)
    key = agent.identity
    if key in memo:
        xprompt = memo.pop(key)
        memo[key] = xprompt
        if xprompt is not None:
            document.with_identity_header(identity.with_xprompt(xprompt))
        return
    if _agent_may_show_xprompt(agent):
        document.with_identity_header(identity.with_xprompt_pending())


__all__ = [
    "attach_memoized_xprompt",
    "attach_xprompt_to_identity",
    "memoize_xprompt",
]
