"""Helpers for inferring bead metadata from agent records."""

from __future__ import annotations

import re

from .agent import Agent

_DISMISSED_AGENT_PREFIX_RE = re.compile(r"^\d{6}\.")
_PHASE_BEAD_AGENT_NAME_RE = re.compile(r"^.+\.\d+$")


def derive_agent_bead_id(agent: Agent) -> str | None:
    """Infer a bead id from an agent name written by ``sase bead work``."""
    if not agent.agent_name:
        return None

    normalized = _DISMISSED_AGENT_PREFIX_RE.sub("", agent.agent_name, count=1)
    if not normalized:
        return None

    if normalized.endswith(".land"):
        epic_id = normalized.removesuffix(".land")
        return epic_id or None

    if _PHASE_BEAD_AGENT_NAME_RE.match(normalized):
        return normalized

    return None
