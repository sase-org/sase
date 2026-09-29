"""Shared fixtures for tribe panel flicker regression splits."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType

FLICKER_NOW = datetime(2026, 7, 18, 16, 0, 0)


def make_tribe_flicker_agent(name: str, suffix: str, **overrides: object) -> Agent:
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": "/tmp/demo.sase",
        "status": "DONE",
        "start_time": FLICKER_NOW,
        "stop_time": FLICKER_NOW,
        "raw_suffix": suffix,
        "agent_name": name,
        "tribe": "epic",
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]
