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


def _lookup_bead_description(bead_id: str) -> str | None:
    """Return the raw persisted description for *bead_id*, if available."""
    try:
        from sase.bead.cli_common import get_read_view

        with get_read_view() as view:
            issue = view.show(bead_id)
    except Exception:
        return None

    return issue.description


def _normalize_bead_description(description: str | None) -> str | None:
    """Collapse bead descriptions for display on a single metadata line."""
    if not description:
        return None
    normalized = " ".join(description.split())
    return normalized or None


def format_agent_bead_display(
    agent: Agent, *, include_description: bool = True
) -> str | None:
    """Format the bead metadata value for an agent details header."""
    bead_id = derive_agent_bead_id(agent)
    if not bead_id:
        return None

    if include_description:
        description = _normalize_bead_description(_lookup_bead_description(bead_id))
        if description:
            return f"{bead_id} - {description}"

    return bead_id
