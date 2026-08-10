"""Shared builders for agent list entry tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.agent.running import RunningAgentInfo
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.time import get_timezone


def agent(**overrides: Any) -> RunningAgentInfo:
    tz = get_timezone()
    defaults = {
        "name": "alpha",
        "project": "sase",
        "pid": 1234,
        "model": "opus",
        "provider": "claude",
        "workspace_num": 11,
        "duration": "5m",
        "approve": False,
        "prompt": "Fix the thing",
        "status": "RUNNING",
        "started_at": datetime(2026, 7, 9, 12, 0, tzinfo=tz),
        "duration_seconds": 300,
        "artifacts_dir": "/tmp/sase/artifacts/ace-run/20260709120000",
    }
    defaults.update(overrides)
    return RunningAgentInfo(**defaults)


def record(**overrides: Any) -> AgentArtifactRecordWire:
    defaults = {
        "project_name": "sase",
        "project_dir": "/tmp/sase",
        "project_file": "/tmp/sase/sase.gp",
        "workflow_dir_name": "ace-run",
        "artifact_dir": "/tmp/sase/artifacts/ace-run/20260709120000",
        "timestamp": "20260709120000",
    }
    defaults.update(overrides)
    return AgentArtifactRecordWire(**defaults)
