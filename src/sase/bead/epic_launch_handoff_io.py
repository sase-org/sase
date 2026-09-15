"""Persistence helpers for epic launch completion handoffs."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.logs._bounded import log_file_lock

from sase.bead.epic_launch_handoff_model import (
    DeferredCompletion,
    EPIC_LAUNCH_TAGS,
    nonempty_str,
)


def epic_completion_key(artifacts_dir: str | Path | None) -> str | None:
    """Return the workflow-independent planner identity for an artifact path."""
    if artifacts_dir is None:
        return None
    try:
        info = parse_agent_artifact_path(artifacts_dir)
    except Exception:
        return None
    if info is None:
        return None
    return f"{info.project_name}__{info.timestamp}"


def read_plan_file(artifacts_dir: str | Path) -> str | None:
    try:
        value = read_json_object(Path(artifacts_dir) / "plan_path.json").get(
            "plan_path"
        )
    except Exception:
        return None
    return str(value) if isinstance(value, str) and value else None


def read_epic_launch_argv(artifacts_dir: str | Path) -> list[str] | None:
    try:
        value = read_json_object(Path(artifacts_dir) / "epic_launch_argv.json").get(
            "argv"
        )
    except Exception:
        return None
    if not isinstance(value, list):
        return None
    argv = [str(item) for item in value]
    return argv or None


def read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def read_agent_meta(artifacts_dir: str | Path) -> dict[str, Any]:
    try:
        return read_json_object(Path(artifacts_dir) / "agent_meta.json")
    except Exception:
        return {}


def optional_str(value: object) -> str | None:
    return nonempty_str(value)


def write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(dict(value), stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def restore_pending(path: Path, deferred: DeferredCompletion) -> None:
    try:
        with log_file_lock(path):
            if not path.exists():
                write_json_atomic(path, deferred.to_dict())
    except Exception:
        pass


def active_epic_launch_keys() -> set[str]:
    from sase.procs import (
        ACTIVE_PROC_STATUSES,
        COMMAND_PROC_KIND,
        DETACHED_PROC_KIND,
        read_procs,
    )

    try:
        tasks = read_procs(
            status=ACTIVE_PROC_STATUSES,
            kind={COMMAND_PROC_KIND, DETACHED_PROC_KIND},
        )
    except Exception:
        return set()
    keys: set[str] = set()
    for task in tasks:
        if not EPIC_LAUNCH_TAGS.issubset(task.tags):
            continue
        artifacts_dir = _command_option(task.command, "--artifacts-dir")
        key = epic_completion_key(artifacts_dir)
        if key is not None:
            keys.add(key)
    return keys


def _command_option(command: list[str], option: str) -> str | None:
    try:
        index = command.index(option)
        return command[index + 1]
    except (ValueError, IndexError):
        return None


def artifact_timestamp(artifacts_dir: str | Path | None) -> str | None:
    if artifacts_dir is None:
        return None
    try:
        info = parse_agent_artifact_path(artifacts_dir)
    except Exception:
        info = None
    if info is not None and info.timestamp:
        return info.timestamp
    name = Path(artifacts_dir).expanduser().name
    return name or None


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def age_seconds(timestamp: str, now: datetime) -> float:
    created = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return max(0.0, (now.astimezone(UTC) - created.astimezone(UTC)).total_seconds())
