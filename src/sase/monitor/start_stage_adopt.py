"""Adopt a staged monitor member from its frozen payload.

The implementation is split into private modules by launch flow, proc adoption,
context reconstruction, and prepared-completion binding. This module preserves the
public import path and the historical ``launch_monitor`` monkeypatch target.
"""

from __future__ import annotations

from ._start_stage_adopt_flow import (
    launch_staged_payload,
    load_staged_monitor_launch_payload,
)
from .models import MonitorRecord
from .start_launch import launch_monitor


def launch_from_persisted_payload(
    artifacts_dir: str,
    *,
    starter_continuation_node_id: str | None = None,
) -> MonitorRecord:
    """Launch a staged monitor from its frozen payload under the lane lock."""
    payload = load_staged_monitor_launch_payload(artifacts_dir)
    return launch_staged_payload(
        artifacts_dir,
        payload,
        starter_continuation_node_id=starter_continuation_node_id,
        launch_callback=launch_monitor,
    )


__all__ = ["launch_from_persisted_payload"]
