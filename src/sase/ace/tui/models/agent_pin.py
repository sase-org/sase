"""Agent pin tribe — the constant and the predicate that derives ``pinned``.

Pinning is implemented as ``Agent.tribe == DEFAULT_PINNED_TRIBE`` (no separate
``pinned`` field), so this module holds the canonical tribe string and the
:func:`is_pinned` helper. Living under ``tui/models`` keeps the dependency
direction one-way: the agent_query evaluator can import this without
dragging in any TUI/action code.
"""

from __future__ import annotations

from .agent import Agent

DEFAULT_PINNED_TRIBE = "pinned"


def is_pinned(agent: Agent) -> bool:
    """Return whether *agent* carries the default pin tribe."""
    return agent.tribe == DEFAULT_PINNED_TRIBE
