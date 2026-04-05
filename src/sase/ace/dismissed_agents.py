"""Persistent tracking of dismissed agents across sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tui.models.agent import Agent, AgentType

_DISMISSED_AGENTS_FILE = Path.home() / ".sase" / "dismissed_agents.json"
_DISMISSED_BUNDLES_DIR = Path.home() / ".sase" / "dismissed_bundles"
_OLD_BUNDLES_FILE = Path.home() / ".sase" / "dismissed_agent_bundles.json"


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
    """Save dismissed agent identities to disk.

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
        with open(_DISMISSED_AGENTS_FILE, "w") as f:
            json.dump(entries, f, indent=2)
        return True
    except OSError:
        return False


def save_dismissed_bundle(agent: Agent) -> bool:
    """Save a single agent bundle to its own file.

    Args:
        agent: The Agent to serialize. Must have a non-None raw_suffix.

    Returns:
        True if saved successfully, False otherwise.
    """
    if agent.raw_suffix is None:
        return False
    try:
        _DISMISSED_BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
        filepath = _DISMISSED_BUNDLES_DIR / f"{agent.raw_suffix}.json"
        with open(filepath, "w") as f:
            json.dump(agent.to_bundle_dict(), f, indent=2)
        return True
    except OSError:
        return False


def load_dismissed_bundles(suffixes: set[str] | None = None) -> list[Agent]:
    """Load dismissed agent bundles from per-agent files.

    Args:
        suffixes: If provided, load only files matching these raw_suffixes.
                  If None, load all bundle files in the directory.

    Returns:
        List of Agent objects reconstructed from bundle files.
    """
    _maybe_migrate_bundles()

    if not _DISMISSED_BUNDLES_DIR.is_dir():
        return []

    agents: list[Agent] = []
    if suffixes is not None:
        for suffix in suffixes:
            filepath = _DISMISSED_BUNDLES_DIR / f"{suffix}.json"
            agent = _load_bundle_file(filepath)
            if agent is not None:
                agents.append(agent)
    else:
        for filepath in _DISMISSED_BUNDLES_DIR.glob("*.json"):
            agent = _load_bundle_file(filepath)
            if agent is not None:
                agents.append(agent)
    return agents


def _load_bundle_file(filepath: Path) -> Agent | None:
    """Load a single Agent from a bundle JSON file."""
    from .tui.models.agent import Agent

    if not filepath.exists():
        return None
    try:
        with open(filepath) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return Agent.from_bundle_dict(data)
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def remove_bundle_by_identity(
    identity: tuple[Any, str, str | None],
    child_raw_suffixes: set[str] | None = None,
) -> bool:
    """Remove bundle file(s) for an agent and optionally its children.

    Args:
        identity: The (AgentType, cl_name, raw_suffix) identity tuple.
        child_raw_suffixes: Raw suffixes of child agents to also remove.

    Returns:
        True if any files were removed, False otherwise.
    """
    removed = False
    _, _, raw_suffix = identity

    if raw_suffix is not None:
        filepath = _DISMISSED_BUNDLES_DIR / f"{raw_suffix}.json"
        if filepath.exists():
            try:
                filepath.unlink()
                removed = True
            except OSError:
                pass

    if child_raw_suffixes:
        for child_suffix in child_raw_suffixes:
            filepath = _DISMISSED_BUNDLES_DIR / f"{child_suffix}.json"
            if filepath.exists():
                try:
                    filepath.unlink()
                    removed = True
                except OSError:
                    pass

    return removed


def _maybe_migrate_bundles() -> None:
    """One-time migration from monolithic bundles file to per-agent files.

    If the old ``dismissed_agent_bundles.json`` exists, each entry is written
    as an individual file under ``~/.sase/dismissed_bundles/`` and the
    monolithic file is deleted.  Idempotent — skips duplicates.
    """
    if not _OLD_BUNDLES_FILE.exists():
        return

    from .tui.models.agent import Agent

    try:
        with open(_OLD_BUNDLES_FILE) as f:
            data = json.load(f)
        if not isinstance(data, list):
            _OLD_BUNDLES_FILE.unlink()
            return

        _DISMISSED_BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
        for entry in data:
            if not isinstance(entry, dict):
                continue
            try:
                agent = Agent.from_bundle_dict(entry)
                save_dismissed_bundle(agent)
            except (KeyError, ValueError, TypeError):
                continue

        _OLD_BUNDLES_FILE.unlink()
    except (OSError, json.JSONDecodeError):
        pass
