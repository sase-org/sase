"""Artifact-path classification helpers for refresh event handling."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.core.agent_artifact_paths import parse_agent_artifact_path

from ._constants import (
    _AGENTS_RELEVANT_ARTIFACT_MARKERS,
    _LIVE_FILE_REFRESH_STATUSES,
)

if TYPE_CHECKING:
    from ...models import Agent


def _artifact_relative_parts(path: Path) -> tuple[str, ...] | None:
    """Return path components below the first ``artifacts`` segment."""
    try:
        artifacts_idx = path.parts.index("artifacts")
    except ValueError:
        return None
    return path.parts[artifacts_idx + 1 :]


def _is_month_shard(value: str) -> bool:
    return len(value) == 6 and value.isdigit()


def _is_day_shard(value: str) -> bool:
    return len(value) == 2 and value.isdigit() and 1 <= int(value) <= 31


def _is_artifact_timestamp(value: str) -> bool:
    return len(value) == 14 and value.isdigit()


def _is_sharded_ace_run_dir_path(relative_parts: tuple[str, ...]) -> bool:
    if not relative_parts or relative_parts[0] != "ace-run":
        return False
    if len(relative_parts) == 2:
        return _is_month_shard(relative_parts[1])
    if len(relative_parts) == 3:
        return _is_month_shard(relative_parts[1]) and _is_day_shard(relative_parts[2])
    if len(relative_parts) == 4:
        month, day, timestamp = relative_parts[1:]
        return (
            _is_month_shard(month)
            and _is_day_shard(day)
            and _is_artifact_timestamp(timestamp)
            and timestamp.startswith(f"{month}{day}")
        )
    return False


def _is_prompt_step_marker(path: Path) -> bool:
    name = path.name
    return name.startswith("prompt_step_") and name.endswith(".json")


def artifact_path_affects_agents(path: Path) -> bool:
    """Return True when an artifact-tree path can change the Agents rows."""
    relative_parts = _artifact_relative_parts(path)
    if relative_parts is None:
        return False
    if not relative_parts:
        return True
    if path.name == ".ace_refresh_pulse":
        return True

    if path.name in _AGENTS_RELEVANT_ARTIFACT_MARKERS:
        return True
    if _is_prompt_step_marker(path):
        return True

    # Watcher callbacks only carry paths, not inotify masks. A shallow,
    # suffixless path is the best signal available for newly-created or
    # deleted agent-root directories such as:
    #   artifacts/<legacy-agent-dir>
    #   artifacts/<workflow>/<timestamp-or-run-dir>
    if len(relative_parts) <= 2 or _is_sharded_ace_run_dir_path(relative_parts):
        try:
            if path.is_dir():
                return True
        except OSError:
            pass
        return path.suffix == ""

    return False


def artifact_dir_from_known_marker_path(path: Path) -> Path | None:
    """Return the exact artifact dir for loader-visible marker writes."""
    relative_parts = _artifact_relative_parts(path)
    if relative_parts is None or len(relative_parts) < 2:
        return None
    if path.name in _AGENTS_RELEVANT_ARTIFACT_MARKERS:
        return path.parent
    if _is_prompt_step_marker(path):
        return path.parent
    return None


def _looks_like_agent_artifact_dir_path(relative_parts: tuple[str, ...]) -> bool:
    """Return True for a specific per-agent artifact directory path."""
    if len(relative_parts) == 1:
        return _is_artifact_timestamp(relative_parts[0])
    if len(relative_parts) == 2:
        return _is_artifact_timestamp(relative_parts[1])
    if len(relative_parts) == 4:
        return _is_sharded_ace_run_dir_path(relative_parts)
    return False


def artifact_dir_from_directory_path(path: Path) -> Path | None:
    """Return the exact artifact dir for a directory-level artifact event."""
    relative_parts = _artifact_relative_parts(path)
    if relative_parts is None or not relative_parts:
        return None
    if path.suffix != "":
        return None
    if not _looks_like_agent_artifact_dir_path(relative_parts):
        return None

    try:
        parsed = parse_agent_artifact_path(path)
    except (ImportError, AttributeError, OSError, RuntimeError, ValueError):
        parsed = None
    if parsed is not None:
        return Path(parsed.artifact_dir)
    return path


def agent_has_live_file_panel(agent: Agent) -> bool:
    """Return True when the detail view can live-refresh this row's file panel."""
    if agent.status not in _LIVE_FILE_REFRESH_STATUSES:
        return False
    return not (agent.is_workflow_child and agent.step_type in ("bash", "python"))
