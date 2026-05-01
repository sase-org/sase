"""Helpers for inferring bead metadata from agent records."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .agent import Agent

if TYPE_CHECKING:
    from sase.bead.model import Issue

_DISMISSED_AGENT_PREFIX_RE = re.compile(r"^\d{6}\.")
_PHASE_BEAD_AGENT_NAME_RE = re.compile(r"^.+\.\d+$")


def _normalized_agent_name(agent: Agent) -> str | None:
    if not agent.agent_name:
        return None

    normalized = _DISMISSED_AGENT_PREFIX_RE.sub("", agent.agent_name, count=1)
    if not normalized:
        return None
    return normalized


def _is_land_agent_name(normalized_agent_name: str | None) -> bool:
    if not normalized_agent_name:
        return False
    return normalized_agent_name.endswith(".land") and bool(
        normalized_agent_name.removesuffix(".land")
    )


def derive_agent_bead_id(agent: Agent) -> str | None:
    """Infer a bead id from an agent name written by ``sase bead work``."""
    normalized = _normalized_agent_name(agent)
    if not normalized:
        return None

    if _is_land_agent_name(normalized):
        epic_id = normalized.removesuffix(".land")
        return epic_id or None

    if _PHASE_BEAD_AGENT_NAME_RE.match(normalized):
        return normalized

    return None


def _lookup_bead_issue(bead_id: str) -> Issue | None:
    """Return the persisted issue for *bead_id*, if available."""
    try:
        from sase.bead.cli_common import get_read_view

        with get_read_view() as view:
            issue = view.show(bead_id)
    except Exception:
        return None

    return issue


def _normalize_bead_text(text: str | None) -> str | None:
    """Collapse bead text for display on a single metadata line."""
    if not text:
        return None
    normalized = " ".join(text.split())
    return normalized or None


def format_agent_bead_display(
    agent: Agent, *, include_description: bool = True
) -> str | None:
    """Format the bead metadata value for an agent details header."""
    bead_id = derive_agent_bead_id(agent)
    if not bead_id:
        return None

    if include_description:
        issue = _lookup_bead_issue(bead_id)
        description = _normalize_bead_text(getattr(issue, "description", None))
        if description:
            return f"{bead_id} - {description}"
        if issue is not None and _is_land_agent_name(_normalized_agent_name(agent)):
            title = _normalize_bead_text(getattr(issue, "title", None))
            if title:
                return f"{bead_id} - Land epic: {title}"

    return bead_id
