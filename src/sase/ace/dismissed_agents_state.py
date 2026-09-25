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


def _save_dismissed_agents(
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


def update_dismissed_agents(
    dismissed_agents_file: Path,
    additions: Iterable[DismissedIdentity] = (),
    removals: Iterable[DismissedIdentity] = (),
) -> set[DismissedIdentity]:
    """Apply removals then additions to the dismissed index, returning the result.

    Uses the atomic locked merge in the Rust binding so concurrent writers
    (persist-cleanup procs, runners, other TUIs) cannot lose each other's
    dismissals; without the binding it falls back to load-modify-save.

    Raises:
        OSError: If the index could not be written.
    """
    added = list(additions)
    removed = list(removals)
    if not added and not removed:
        return load_dismissed_agents(dismissed_agents_file)
    try:
        from sase.core.agent_cleanup_execution import (
            try_update_dismissed_agents_index,
        )

        updated = try_update_dismissed_agents_index(
            dismissed_agents_file,
            [_identity_to_entry(identity) for identity in added],
            [_identity_to_entry(identity) for identity in removed],
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
    current.difference_update(removed)
    current.update(added)
    if not _save_dismissed_agents(dismissed_agents_file, current):
        raise OSError(f"failed to write dismissed index {dismissed_agents_file}")
    return current


def add_dismissed_agents(
    dismissed_agents_file: Path,
    identities: Iterable[DismissedIdentity],
) -> set[DismissedIdentity]:
    """Add identities to the dismissed index, returning the resulting set."""
    return update_dismissed_agents(dismissed_agents_file, additions=identities)


def remove_dismissed_agents(
    dismissed_agents_file: Path,
    identities: Iterable[DismissedIdentity],
) -> set[DismissedIdentity]:
    """Remove identities from the dismissed index, returning the resulting set."""
    return update_dismissed_agents(dismissed_agents_file, removals=identities)
