"""Persistent tracking of custom agent ordering across sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tui.models.agent import AgentType

_AGENT_ORDER_FILE = Path.home() / ".sase" / "agent_order.json"


def load_agent_order() -> list[tuple[AgentType, str, str | None]]:
    """Load custom agent order from disk.

    Returns:
        List of (AgentType, cl_name, raw_suffix) tuples in user's desired order.
    """
    from .tui.models.agent import AgentType

    if not _AGENT_ORDER_FILE.exists():
        return []

    try:
        with open(_AGENT_ORDER_FILE) as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []

        result: list[tuple[AgentType, str, str | None]] = []
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
            result.append((agent_type, cl_name, raw_suffix))
        return result
    except (OSError, json.JSONDecodeError):
        return []


def save_agent_order(
    order: list[tuple[AgentType, str, str | None]],
) -> bool:
    """Save custom agent order to disk.

    Args:
        order: List of (AgentType, cl_name, raw_suffix) tuples.

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        _AGENT_ORDER_FILE.parent.mkdir(parents=True, exist_ok=True)
        entries = [
            [agent_type.value, cl_name, raw_suffix]
            for agent_type, cl_name, raw_suffix in order
        ]
        with open(_AGENT_ORDER_FILE, "w") as f:
            json.dump(entries, f, indent=2)
        return True
    except OSError:
        return False
