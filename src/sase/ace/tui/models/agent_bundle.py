"""Serialization and deserialization for Agent instances."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any

from sase.ace.tui.models.agent import Agent, AgentType


def to_bundle_dict(agent: Agent) -> dict[str, Any]:
    """Serialize an Agent to a dict for bundle persistence.

    Converts AgentType to string and datetime to ISO format string.
    """
    result: dict[str, Any] = {}
    for f in dataclasses.fields(agent):
        if f.name in (
            "followup_agents",
            "attempt_history",
            "_loaded_from_dismissed_bundle",
            "tag",
        ):
            continue
        value = getattr(agent, f.name)
        if isinstance(value, AgentType):
            value = value.value
        elif isinstance(value, datetime):
            value = value.isoformat()
        elif isinstance(value, list) and value and isinstance(value[0], datetime):
            value = [v.isoformat() for v in value]
        result[f.name] = value
    return result


def from_bundle_dict(data: dict[str, Any]) -> Agent:
    """Reconstruct an Agent from a bundle dict.

    Uses .get() with defaults for forward-compatibility with new fields.
    """
    # Map removed AgentType values to RUNNING for backward compatibility
    _LEGACY_AGENT_TYPES = {"fix-hook", "summarize", "mentor", "crs"}
    raw_type = data["agent_type"]
    if raw_type in _LEGACY_AGENT_TYPES:
        agent_type = AgentType.RUNNING
    else:
        agent_type = AgentType(raw_type)
    start_time = data.get("start_time")
    if isinstance(start_time, str):
        start_time = datetime.fromisoformat(start_time)

    kwargs: dict[str, Any] = {
        "agent_type": agent_type,
        "cl_name": data["cl_name"],
        "project_file": data["project_file"],
        "status": data["status"],
        "start_time": start_time,
    }

    # Backward compat: old bundles stored singular datetime fields
    for old, new in (
        ("plan_time", "plan_times"),
        ("feedback_time", "feedback_times"),
        ("questions_time", "questions_times"),
    ):
        if old in data and new not in data:
            raw = data.pop(old)
            if isinstance(raw, str):
                data[new] = [raw]

    # Populate all optional fields from the bundle
    _DATETIME_FIELDS = {
        "run_start_time",
        "stop_time",
        "code_time",
    }
    _DATETIME_LIST_FIELDS = {
        "plan_times",
        "feedback_times",
        "questions_times",
        "retry_times",
    }
    for f in dataclasses.fields(Agent):
        if f.name in kwargs:
            continue
        if f.name not in data:
            continue
        value = data[f.name]
        # Skip None values for fields with non-None defaults (list fields)
        if value is None and f.default_factory is not dataclasses.MISSING:  # type: ignore[comparison-overlap]
            continue
        # Deserialize ISO datetime strings for datetime fields
        if f.name in _DATETIME_FIELDS and isinstance(value, str):
            value = datetime.fromisoformat(value)
        elif f.name in _DATETIME_LIST_FIELDS and isinstance(value, list):
            value = [
                datetime.fromisoformat(v) if isinstance(v, str) else v for v in value
            ]
        kwargs[f.name] = value

    return Agent(**kwargs)
