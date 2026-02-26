"""Persistent tracking of dismissed agents across sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tui.models.agent import Agent, AgentType

MAX_DISMISSED = 500
_DISMISSED_AGENTS_FILE = Path.home() / ".sase" / "dismissed_agents.json"
_DISMISSED_BUNDLES_FILE = Path.home() / ".sase" / "dismissed_agent_bundles.json"


def load_dismissed_agents() -> set[tuple[AgentType, str, str | None]]:
    """Load dismissed agent identities from disk.

    Returns:
        Set of (AgentType, cl_name, raw_suffix) tuples.
    """
    from .tui.models.agent import AgentType

    if not _DISMISSED_AGENTS_FILE.exists():
        return set()

    try:
        with open(_DISMISSED_AGENTS_FILE) as f:
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


def save_dismissed_agents(
    dismissed: set[tuple[AgentType, str, str | None]],
) -> bool:
    """Save dismissed agent identities to disk, trimming if over limit.

    Args:
        dismissed: Set of (AgentType, cl_name, raw_suffix) tuples.

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        _DISMISSED_AGENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        entries = [
            [agent_type.value, cl_name, raw_suffix]
            for agent_type, cl_name, raw_suffix in dismissed
        ]
        # Trim to MAX_DISMISSED, dropping oldest entries first.
        # Sort by raw_suffix (timestamp) descending so newest are kept.
        if len(entries) > MAX_DISMISSED:
            entries.sort(key=lambda e: e[2] or "", reverse=True)
            entries = entries[:MAX_DISMISSED]
        with open(_DISMISSED_AGENTS_FILE, "w") as f:
            json.dump(entries, f, indent=2)
        return True
    except OSError:
        return False


def load_dismissed_bundles() -> list[Agent]:
    """Load dismissed agent bundles from disk.

    Returns:
        List of Agent objects reconstructed from bundle dicts.
    """
    from .tui.models.agent import Agent

    if not _DISMISSED_BUNDLES_FILE.exists():
        return []

    try:
        with open(_DISMISSED_BUNDLES_FILE) as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []

        agents: list[Agent] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            try:
                agents.append(Agent.from_bundle_dict(entry))
            except (KeyError, ValueError, TypeError):
                continue
        return agents
    except (OSError, json.JSONDecodeError):
        return []


def save_dismissed_bundles(agents: list[Agent]) -> bool:
    """Save dismissed agent bundles to disk, trimming if over limit.

    Args:
        agents: List of Agent objects to serialize.

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        _DISMISSED_BUNDLES_FILE.parent.mkdir(parents=True, exist_ok=True)
        entries = [a.to_bundle_dict() for a in agents]
        # Trim to MAX_DISMISSED, keeping newest (sort by raw_suffix descending)
        if len(entries) > MAX_DISMISSED:
            entries.sort(key=lambda e: e.get("raw_suffix") or "", reverse=True)
            entries = entries[:MAX_DISMISSED]
        with open(_DISMISSED_BUNDLES_FILE, "w") as f:
            json.dump(entries, f, indent=2)
        return True
    except OSError:
        return False


def remove_bundle_by_identity(
    identity: tuple[Any, str, str | None],
) -> bool:
    """Remove a bundle (and its child step bundles) by agent identity.

    Args:
        identity: The (AgentType, cl_name, raw_suffix) identity tuple.

    Returns:
        True if any bundles were removed, False otherwise.
    """
    bundles = load_dismissed_bundles()
    if not bundles:
        return False

    _, _, raw_suffix = identity

    original_len = len(bundles)
    bundles = [
        b
        for b in bundles
        if not (
            # Match the agent itself
            b.identity == identity
            # Match child steps (parent_timestamp matches raw_suffix)
            or (raw_suffix is not None and b.parent_timestamp == raw_suffix)
        )
    ]

    if len(bundles) == original_len:
        return False

    save_dismissed_bundles(bundles)
    return True
