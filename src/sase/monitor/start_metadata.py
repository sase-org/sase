"""Metadata reads shared by the monitor-start internals."""

from __future__ import annotations

import json
import os
from typing import Any

from .models import MonitorError


def read_start_meta(artifacts_dir: str) -> dict[str, Any]:
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    with open(meta_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise MonitorError(f"agent_meta.json at {artifacts_dir!r} is not an object")
    return data


def persist_monitor_running_state(artifacts_dir: str) -> None:
    """Mark the member running and clear any not-adopted held flag."""
    from sase.axe.run_agent_helpers_artifacts import update_meta_fields

    update_meta_fields(
        artifacts_dir,
        {"monitor_state": "running"},
        remove_keys=("monitor_stage_held",),
    )


__all__ = [
    "persist_monitor_running_state",
    "read_start_meta",
]
