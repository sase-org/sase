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
            "runtime_children",
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
        elif isinstance(value, dict) and value:
            value = {
                k.isoformat() if isinstance(k, datetime) else k: v
                for k, v in value.items()
            }
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
        "epic_time",
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
        elif f.name == "feedback_plan_paths" and isinstance(value, dict):
            parsed_paths: dict[datetime, str] = {}
            for k, v in value.items():
                if not isinstance(v, str):
                    continue
                if isinstance(k, datetime):
                    parsed_paths[k] = v
                    continue
                if isinstance(k, str):
                    try:
                        parsed_paths[datetime.fromisoformat(k)] = v
                    except ValueError:
                        continue
            value = parsed_paths
        kwargs[f.name] = value

    agent = Agent(**kwargs)
    _synthesize_dismissed_name(agent)
    return agent


def _synthesize_dismissed_name(agent: Agent) -> None:
    """Repair old dismissed bundles missing ``agent_name``.

    Older bundles were saved before the sase-10 dismissal-rename rolled
    out and so lack ``agent_name``. Loading should produce a stable
    prefixed name without requiring the user to revive and re-dismiss
    them. We derive a base from ``cl_name``/``raw_suffix`` and tag it
    with the best-known completion date.
    """
    from sase.agent.names import (
        add_dismissed_prefix,
        is_dismissed_prefixed,
        strip_dismissed_prefix,
    )

    if agent.agent_name and is_dismissed_prefixed(agent.agent_name):
        return

    # Only synthesize for top-level agents — workflow children inherit
    # the parent's prefixed identity through ``parent_timestamp`` and
    # were not expected to carry an ``agent_name`` in older bundles.
    if agent.is_workflow_child:
        return

    completion = agent.stop_time or agent.start_time
    if completion is None and agent.raw_suffix:
        try:
            completion = datetime.strptime(agent.raw_suffix[:14], "%Y%m%d%H%M%S")
        except ValueError:
            completion = None
    if completion is None:
        return

    base = agent.agent_name
    if base:
        base = strip_dismissed_prefix(base)
    else:
        if agent.cl_name and agent.cl_name != "unknown":
            base = agent.cl_name
        elif agent.raw_suffix:
            base = agent.raw_suffix
    if not base:
        return

    agent.agent_name = add_dismissed_prefix(base, completion)
