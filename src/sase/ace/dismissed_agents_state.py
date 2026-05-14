"""Persistent dismissed agent identity state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tui.models.agent import AgentType


def load_dismissed_agents(
    dismissed_agents_file: Path,
) -> set[tuple[AgentType, str, str | None]]:
    """Load dismissed agent identities from disk.

    Returns:
        Set of (AgentType, cl_name, raw_suffix) tuples.
    """
    from .tui.models.agent import AgentType

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
    content = _dismissed_agents_json_content(entries)

    def direct_writer() -> bool:
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
            with open(dismissed_agents_file, "w") as f:
                f.write(content)
            return True
        except OSError:
            return False

    try:
        from sase.daemon.agent_writes import (
            atomic_json_export,
            daemon_agent_write,
            write_agent_metadata_or_fallback,
        )

        previous = load_dismissed_agents(dismissed_agents_file)
        next_by_key = {
            (agent_type.value, cl_name, raw_suffix): True
            for agent_type, cl_name, raw_suffix in dismissed
        }
        previous_by_key = {
            (agent_type.value, cl_name, raw_suffix): False
            for agent_type, cl_name, raw_suffix in previous
        }
        identity_states = previous_by_key | next_by_key
        export = atomic_json_export(dismissed_agents_file, content)

        def daemon_writer(client: Any) -> bool:
            if not identity_states:
                daemon_agent_write(
                    client,
                    "agents.cleanup_result",
                    project_id="global",
                    payload={"dismissed_identities": [], "active_count": 0},
                    source_exports=[export],
                )
                return True

            ordered = sorted(
                identity_states.items(),
                key=lambda item: (item[0][0], item[0][1], item[0][2] or ""),
            )
            for idx, ((agent_type, cl_name, raw_suffix), active) in enumerate(ordered):
                identity = {
                    "schema_version": 1,
                    "agent_type": agent_type,
                    "cl_name": cl_name,
                    "raw_suffix": raw_suffix,
                    "agent_id": None,
                    "dismissed_name": cl_name,
                    "active": active,
                }
                daemon_agent_write(
                    client,
                    "agents.dismissed_identity",
                    project_id="global",
                    payload={"identity": identity},
                    source_exports=[export] if idx == len(ordered) - 1 else [],
                )
            return True

        return write_agent_metadata_or_fallback(
            "agents.dismissed_identity",
            daemon_writer=daemon_writer,
            direct_writer=direct_writer,
        )
    except (OSError, ValueError):
        return direct_writer()


def _dismissed_agents_json_content(entries: list[dict[str, Any]]) -> str:
    legacy_entries = [
        [entry["agent_type"], entry["cl_name"], entry["raw_suffix"]]
        for entry in entries
    ]
    return json.dumps(legacy_entries, indent=2) + "\n"
