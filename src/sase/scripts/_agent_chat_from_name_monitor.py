"""Monitor/proc source resolution for named-agent fork sources."""

from __future__ import annotations

from pathlib import Path

from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.monitor.models import MonitorRecord
from sase.monitor.store import read_monitor_marker
from sase.scripts._agent_chat_from_name_models import ForkSource
from sase.scripts._fork_proc_sources import proc_info_from_monitor


def resolve_monitor_fork_source(name: str, artifacts_dir: Path) -> ForkSource:
    """Resolve one explicitly named monitor family member as a proc source."""
    record = read_family_monitor_marker(artifacts_dir)
    if record is None:
        raise RuntimeError(f"No agent with chat history found for: {name}")
    return ForkSource(
        kind="proc",
        name=name,
        path="",
        proc=proc_info_from_monitor(record),
    )


def read_family_monitor_marker(artifacts_dir: Path) -> MonitorRecord | None:
    project_name = _project_name_for_artifact_dir(artifacts_dir)
    return read_monitor_marker(project_name, str(artifacts_dir))


def _project_name_for_artifact_dir(artifact_dir: Path) -> str:
    try:
        info = parse_agent_artifact_path(artifact_dir)
    except (OSError, RuntimeError, ValueError):
        return ""
    return info.project_name if info is not None else ""
