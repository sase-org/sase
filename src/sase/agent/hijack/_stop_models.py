"""Shared types and file helpers for the hijack stop protocol."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Callable


@dataclass
class HijackTarget:
    """Resolved facts about the agent row about to be hijacked."""

    name: str
    artifacts_dir: str
    project_name: str
    project_file: str
    artifacts_timestamp: str
    is_home: bool
    pid: int | None
    claim_pid: int | None
    claim_pinned: bool
    cl_name: str | None
    workflow: str | None
    workspace_num: int | None
    workspace_dir: str | None
    status: str
    lifecycle_phase: str | None
    is_monitor_turn: bool
    is_gate_turn: bool
    agent_session: str | None
    capabilities: list[str]
    model_alias: str | None
    model_alias_trail: list[str]
    model_origin: str | None
    provider: str | None
    model: str | None
    effort: str | None
    run_started_at: float | None
    done_outcome: str | None
    done_recovery: dict[str, Any] | None


@dataclass
class StopDeps:
    """Seams for tests; production uses the defaults."""

    find_agent: Callable[[str], Any | None] | None = None
    list_running: Callable[[], list[Any]] | None = None
    terminate: Callable[..., Any] | None = None
    snapshot_repo: Callable[..., Any] | None = None
    now: Callable[[], float] | None = None


def read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_done_marker(artifacts_dir: str) -> tuple[str | None, dict[str, Any] | None]:
    data = read_json_dict(Path(artifacts_dir) / "done.json")
    if data is None:
        return None, None
    outcome = data.get("outcome")
    recovery = data.get("recovery")
    return (
        outcome if isinstance(outcome, str) else None,
        dict(recovery) if isinstance(recovery, dict) else None,
    )


__all__ = [
    "HijackTarget",
    "StopDeps",
    "read_done_marker",
    "read_json_dict",
]
