"""Durable user-kill intent markers and recorded agent identity reads."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sase.agent._user_kill_types import (
    USER_KILL_INTENT_MARKER,
    AgentTerminationResult,
)
from sase.agent.process_tree import process_is_running
from sase.core.process_identity import (
    pid_is_thread,
    process_identity_matches,
    process_identity_token,
)

_SCRATCH_KEY_META_FIELD = "launch_scratch_key"


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def user_kill_intent_path(artifacts_dir: str | Path) -> Path:
    return Path(artifacts_dir) / USER_KILL_INTENT_MARKER


def write_user_kill_intent(
    artifacts_dir: str | Path | None,
    *,
    pid: int,
    source: str,
    reason: str | None = None,
    timestamp: float | None = None,
) -> Path | None:
    """Persist explicit user-kill intent before signalling an agent."""
    if artifacts_dir is None:
        return None
    marker_path = user_kill_intent_path(artifacts_dir)
    marker_data: dict[str, Any] = {
        "schema_version": 1,
        "timestamp": time.time() if timestamp is None else timestamp,
        "pid": pid,
        "source": source,
    }
    if reason:
        marker_data["reason"] = reason
    try:
        _atomic_write_json(marker_path, marker_data)
    except OSError:
        return None
    return marker_path


def _read_user_kill_intent(artifacts_dir: str | Path) -> dict[str, Any] | None:
    """Read the durable user-kill intent marker without deleting it."""
    try:
        with open(user_kill_intent_path(artifacts_dir), encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def has_user_kill_intent(artifacts_dir: str | Path) -> bool:
    return _read_user_kill_intent(artifacts_dir) is not None


def ensure_user_kill_intent(
    artifacts_dir: str | Path | None,
    *,
    pid: int,
    source: str,
    reason: str | None = None,
) -> Path | None:
    """Return the intent marker path, writing one only when none exists yet.

    The durable stage usually finds the marker the interactive stage wrote and
    must not overwrite its timestamp or source; a dismissal safety net finds
    none and records the user's intent itself so the runner classifies the
    signal as a user kill.
    """
    if artifacts_dir is None:
        return None
    if has_user_kill_intent(artifacts_dir):
        return user_kill_intent_path(artifacts_dir)
    return write_user_kill_intent(artifacts_dir, pid=pid, source=source, reason=reason)


def record_user_kill_result(
    marker_path: str | Path | None, result: AgentTerminationResult
) -> None:
    if marker_path is None:
        return
    path = Path(marker_path)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["result"] = asdict(result)
    data["result_timestamp"] = time.time()
    try:
        _atomic_write_json(path, data)
    except OSError:
        pass


def _read_agent_meta_field(artifacts_dir: str | Path | None, field: str) -> object:
    if artifacts_dir is None:
        return None
    for marker_name in ("agent_meta.json", "running.json"):
        try:
            with open(Path(artifacts_dir) / marker_name, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and field in data:
            return data.get(field)
    return None


def _read_recorded_process_identity(
    artifacts_dir: str | Path | None,
) -> object | None:
    return _read_agent_meta_field(artifacts_dir, "process_identity")


def read_recorded_scratch_key(artifacts_dir: str | Path | None) -> str | None:
    value = _read_agent_meta_field(artifacts_dir, _SCRATCH_KEY_META_FIELD)
    return value if isinstance(value, str) and value else None


def target_identity_is_verified(
    pid: int,
    *,
    artifacts_dir: str | Path | None,
) -> bool:
    if pid_is_thread(pid):
        return False
    return process_identity_matches(pid, _read_recorded_process_identity(artifacts_dir))


def live_verified_agent_pid(pid: int, *, artifacts_dir: str | Path | None) -> bool:
    """Whether *pid* is running and provably the process the agent recorded.

    Stricter than the identity check a user-requested kill applies: evidence
    that is missing or unreadable counts as *not* verified, because callers use
    this to decide whether to signal a pid nobody explicitly asked to kill.
    """
    recorded = _read_recorded_process_identity(artifacts_dir)
    if not isinstance(recorded, str) or ":" not in recorded:
        return False
    if pid_is_thread(pid) or not process_is_running(pid):
        return False
    return process_identity_token(pid) == recorded


__all__ = [
    "ensure_user_kill_intent",
    "has_user_kill_intent",
    "live_verified_agent_pid",
    "read_recorded_scratch_key",
    "record_user_kill_result",
    "target_identity_is_verified",
    "user_kill_intent_path",
    "write_user_kill_intent",
]
