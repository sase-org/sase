"""Persistent tracking of pinned agents across sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tui.models.agent import AgentType

_PINNED_AGENTS_FILE = Path.home() / ".sase" / "pinned_agents.json"


def load_pinned_agents() -> set[tuple[AgentType, str, str | None]]:
    """Load pinned agent identities from disk.

    Returns:
        Set of (AgentType, cl_name, raw_suffix) tuples.
    """
    from .tui.models.agent import AgentType

    if not _PINNED_AGENTS_FILE.exists():
        return set()

    try:
        with open(_PINNED_AGENTS_FILE) as f:
            data = json.load(f)
        if not isinstance(data, list):
            return set()

        result: set[tuple[AgentType, str, str | None]] = set()
        for entry in data:
            if not isinstance(entry, list) or len(entry) != 3:
                continue
            try:
                agent_type = AgentType(entry[0])
            except ValueError:
                continue
            cl_name = entry[1]
            raw_suffix = entry[2]
            if not isinstance(cl_name, str):
                continue
            if raw_suffix is not None and not isinstance(raw_suffix, str):
                continue
            result.add((agent_type, cl_name, raw_suffix))
        return result
    except (OSError, json.JSONDecodeError):
        return set()


def save_pinned_agents(
    pinned: set[tuple[AgentType, str, str | None]],
) -> bool:
    """Save pinned agent identities to disk.

    Args:
        pinned: Set of (AgentType, cl_name, raw_suffix) tuples.

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        _PINNED_AGENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        entries = [
            [agent_type.value, cl_name, raw_suffix]
            for agent_type, cl_name, raw_suffix in pinned
        ]
        with open(_PINNED_AGENTS_FILE, "w") as f:
            json.dump(entries, f, indent=2)
        return True
    except OSError:
        return False


def toggle_pinned_agent(
    pinned: set[tuple[AgentType, str, str | None]],
    identity: tuple[AgentType, str, str | None],
) -> bool:
    """Toggle an agent's pinned state.

    Args:
        pinned: The current set of pinned identities (mutated in place).
        identity: The agent identity to toggle.

    Returns:
        True if the agent is now pinned, False if unpinned.
    """
    if identity in pinned:
        pinned.discard(identity)
        return False
    else:
        pinned.add(identity)
        return True
