"""Shared helpers for explicit user-requested agent termination."""

from __future__ import annotations

import json
import os
import signal
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sase.core.process_identity import pid_is_thread, process_identity_matches

USER_KILL_INTENT_MARKER = ".sase_user_kill_pending"

Killpg = Callable[[int, int], None]
SleepFn = Callable[[float], None]
TimeFn = Callable[[], float]


@dataclass(frozen=True)
class _UserKillResult:
    """Outcome of a user-requested process-group termination attempt."""

    success: bool
    status: str
    pid: int
    pgid: int
    marker_path: str | None = None
    escalated: bool = False
    error: str | None = None


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


def _user_kill_intent_path(artifacts_dir: str | Path) -> Path:
    return Path(artifacts_dir) / USER_KILL_INTENT_MARKER


def _write_user_kill_intent(
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
    marker_path = _user_kill_intent_path(artifacts_dir)
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
        with open(_user_kill_intent_path(artifacts_dir), encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def has_user_kill_intent(artifacts_dir: str | Path) -> bool:
    return _read_user_kill_intent(artifacts_dir) is not None


def _record_user_kill_result(
    marker_path: str | Path | None, result: _UserKillResult
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


def _read_recorded_process_identity(
    artifacts_dir: str | Path | None,
) -> object | None:
    if artifacts_dir is None:
        return None
    for marker_name in ("agent_meta.json", "running.json"):
        try:
            with open(Path(artifacts_dir) / marker_name, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and "process_identity" in data:
            return data.get("process_identity")
    return None


def _target_identity_is_verified(
    pid: int,
    *,
    artifacts_dir: str | Path | None,
) -> bool:
    if pid_is_thread(pid):
        return False
    return process_identity_matches(pid, _read_recorded_process_identity(artifacts_dir))


def _process_group_alive(pgid: int, *, killpg: Killpg) -> bool:
    try:
        killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_exit_or_escalate(
    *,
    pid: int,
    pgid: int,
    marker_path: str | None,
    grace_seconds: float,
    poll_interval: float,
    killpg: Killpg,
    sleep_fn: SleepFn,
    monotonic_fn: TimeFn,
) -> _UserKillResult:
    deadline = monotonic_fn() + max(grace_seconds, 0.0)
    while monotonic_fn() < deadline:
        sleep_fn(max(poll_interval, 0.0))
        if not _process_group_alive(pgid, killpg=killpg):
            result = _UserKillResult(
                True,
                "killed",
                pid,
                pgid,
                marker_path=marker_path,
            )
            _record_user_kill_result(marker_path, result)
            return result

    try:
        killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        result = _UserKillResult(True, "killed", pid, pgid, marker_path=marker_path)
    except PermissionError as exc:
        result = _UserKillResult(
            False,
            "permission_denied",
            pid,
            pgid,
            marker_path=marker_path,
            error=str(exc) or "permission denied",
        )
    else:
        result = _UserKillResult(
            True,
            "force_killed",
            pid,
            pgid,
            marker_path=marker_path,
            escalated=True,
        )
    _record_user_kill_result(marker_path, result)
    return result


def _terminate_process_group(
    pid: int,
    *,
    artifacts_dir: str | Path | None = None,
    wait: bool = True,
    background: bool = False,
    grace_seconds: float = 0.5,
    poll_interval: float = 0.05,
    killpg: Killpg = os.killpg,
    sleep_fn: SleepFn = time.sleep,
    monotonic_fn: TimeFn = time.monotonic,
    marker_path: str | Path | None = None,
) -> _UserKillResult:
    """Terminate a user-killed process group with SIGTERM then SIGKILL fallback."""
    pgid = pid
    marker_str = str(marker_path) if marker_path is not None else None
    if not _target_identity_is_verified(pid, artifacts_dir=artifacts_dir):
        result = _UserKillResult(
            True,
            "identity_mismatch",
            pid,
            pgid,
            marker_path=marker_str,
        )
        _record_user_kill_result(marker_str, result)
        return result
    try:
        killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        result = _UserKillResult(
            True,
            "already_stopped",
            pid,
            pgid,
            marker_path=marker_str,
        )
        _record_user_kill_result(marker_str, result)
        return result
    except PermissionError as exc:
        result = _UserKillResult(
            False,
            "permission_denied",
            pid,
            pgid,
            marker_path=marker_str,
            error=str(exc) or "permission denied",
        )
        _record_user_kill_result(marker_str, result)
        return result

    initial = _UserKillResult(True, "killed", pid, pgid, marker_path=marker_str)
    if not wait:
        _record_user_kill_result(marker_str, initial)
        if background:
            thread = threading.Thread(
                target=_wait_for_exit_or_escalate,
                kwargs={
                    "pid": pid,
                    "pgid": pgid,
                    "marker_path": marker_str,
                    "grace_seconds": grace_seconds,
                    "poll_interval": poll_interval,
                    "killpg": killpg,
                    "sleep_fn": sleep_fn,
                    "monotonic_fn": monotonic_fn,
                },
                name=f"sase-user-kill-{pid}",
                daemon=True,
            )
            thread.start()
        return initial

    return _wait_for_exit_or_escalate(
        pid=pid,
        pgid=pgid,
        marker_path=marker_str,
        grace_seconds=grace_seconds,
        poll_interval=poll_interval,
        killpg=killpg,
        sleep_fn=sleep_fn,
        monotonic_fn=monotonic_fn,
    )


def request_user_kill(
    pid: int,
    *,
    artifacts_dir: str | Path | None,
    source: str,
    reason: str | None = None,
    wait: bool = True,
    background: bool = False,
    grace_seconds: float = 0.5,
    poll_interval: float = 0.05,
    killpg: Killpg = os.killpg,
    sleep_fn: SleepFn = time.sleep,
    monotonic_fn: TimeFn = time.monotonic,
) -> _UserKillResult:
    """Write user-kill intent, then terminate the target process group."""
    marker_path = _write_user_kill_intent(
        artifacts_dir,
        pid=pid,
        source=source,
        reason=reason,
    )
    return _terminate_process_group(
        pid,
        artifacts_dir=artifacts_dir,
        wait=wait,
        background=background,
        grace_seconds=grace_seconds,
        poll_interval=poll_interval,
        killpg=killpg,
        sleep_fn=sleep_fn,
        monotonic_fn=monotonic_fn,
        marker_path=marker_path,
    )


__all__ = [
    "USER_KILL_INTENT_MARKER",
    "has_user_kill_intent",
    "request_user_kill",
]
