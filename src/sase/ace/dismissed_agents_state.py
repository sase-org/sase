"""Persistent dismissed agent identity state."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sase.core.agent_types import AgentType

DismissedIdentity = tuple[AgentType, str, str | None]


def _identity_to_entry(identity: DismissedIdentity) -> dict[str, Any]:
    agent_type, cl_name, raw_suffix = identity
    return {
        "agent_type": agent_type.value,
        "cl_name": cl_name,
        "raw_suffix": raw_suffix,
    }


def _entry_to_identity(entry: Any) -> DismissedIdentity | None:
    if not isinstance(entry, dict):
        return None
    try:
        agent_type = AgentType(entry.get("agent_type"))
    except ValueError:
        return None
    cl_name = entry.get("cl_name")
    raw_suffix = entry.get("raw_suffix")
    if not isinstance(cl_name, str):
        return None
    if raw_suffix is not None and not isinstance(raw_suffix, str):
        return None
    return (agent_type, cl_name, raw_suffix)


def load_dismissed_agents(
    dismissed_agents_file: Path,
) -> set[tuple[AgentType, str, str | None]]:
    """Load dismissed agent identities from disk.

    Returns:
        Set of (AgentType, cl_name, raw_suffix) tuples.
    """
    if not dismissed_agents_file.exists():
        return set()

    try:
        with open(dismissed_agents_file) as f:
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
    dismissed_agents_file: Path,
    dismissed: set[tuple[AgentType, str, str | None]],
) -> bool:
    """Save dismissed agent identities to disk.

    Args:
        dismissed: Set of (AgentType, cl_name, raw_suffix) tuples.

    Returns:
        True if saved successfully, False otherwise.
    """
    entries = [
        {"agent_type": agent_type.value, "cl_name": cl_name, "raw_suffix": raw_suffix}
        for agent_type, cl_name, raw_suffix in sorted(
            dismissed, key=lambda item: (item[0].value, item[1], item[2] or "")
        )
    ]
    try:
        from sase.core.agent_cleanup_execution import (
            try_save_dismissed_agents_index,
        )

        if try_save_dismissed_agents_index(dismissed_agents_file, entries):
            return True
    except (OSError, ValueError):
        return False

    try:
        dismissed_agents_file.parent.mkdir(parents=True, exist_ok=True)
        legacy_entries = [
            [entry["agent_type"], entry["cl_name"], entry["raw_suffix"]]
            for entry in entries
        ]
        with open(dismissed_agents_file, "w") as f:
            json.dump(legacy_entries, f, indent=2)
        return True
    except OSError:
        return False


def add_dismissed_agents(
    dismissed_agents_file: Path,
    identities: Iterable[DismissedIdentity],
) -> set[DismissedIdentity]:
    """Add identities to the dismissed index, returning the resulting set.

    Uses the atomic locked merge when the Rust binding is available so
    concurrent writers cannot lose each other's dismissals; otherwise falls
    back to load-modify-save.
    """
    additions = [_identity_to_entry(identity) for identity in identities]
    try:
        from sase.core.agent_cleanup_execution import (
            try_update_dismissed_agents_index,
        )

        updated = try_update_dismissed_agents_index(
            dismissed_agents_file, additions, []
        )
    except (OSError, ValueError):
        updated = None
    if updated is not None:
        return {
            identity
            for entry in updated
            if (identity := _entry_to_identity(entry)) is not None
        }
    current = load_dismissed_agents(dismissed_agents_file)
    current.update(
        identity
        for entry in additions
        if (identity := _entry_to_identity(entry)) is not None
    )
    save_dismissed_agents(dismissed_agents_file, current)
    return current


def remove_dismissed_agents(
    dismissed_agents_file: Path,
    identities: Iterable[DismissedIdentity],
) -> set[DismissedIdentity]:
    """Remove identities from the dismissed index, returning the resulting set.

    Uses the atomic locked merge when the Rust binding is available so
    concurrent writers cannot lose each other's dismissals; otherwise falls
    back to load-modify-save.
    """
    removals = [_identity_to_entry(identity) for identity in identities]
    try:
        from sase.core.agent_cleanup_execution import (
            try_update_dismissed_agents_index,
        )

        updated = try_update_dismissed_agents_index(dismissed_agents_file, [], removals)
    except (OSError, ValueError):
        updated = None
    if updated is not None:
        return {
            identity
            for entry in updated
            if (identity := _entry_to_identity(entry)) is not None
        }
    current = load_dismissed_agents(dismissed_agents_file)
    current.difference_update(
        identity
        for entry in removals
        if (identity := _entry_to_identity(entry)) is not None
    )
    save_dismissed_agents(dismissed_agents_file, current)
    return current
