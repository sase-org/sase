"""Agent pin tag — the constant and the predicate that derives ``pinned``.

Pinning is implemented as ``Agent.tag == DEFAULT_PINNED_TAG`` (no separate
``pinned`` field), so this module holds the canonical tag string and the
:func:`is_pinned` helper. Living under ``tui/models`` keeps the dependency
direction one-way: the agent_query evaluator can import this without
dragging in any TUI/action code.
"""

from __future__ import annotations

from .agent import Agent

DEFAULT_PINNED_TAG = "pinned"


def is_pinned(agent: Agent) -> bool:
    """Return whether *agent* carries the default pin tag."""
    return agent.tag == DEFAULT_PINNED_TAG
