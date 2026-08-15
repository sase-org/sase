"""Runtime markers and sidecars for one reserved proc-shell."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .paths import procs_dir

_PROC_GO_MARKER = ".proc_go"
_PROC_STARTED_MARKER = ".proc_started"
_REQUEST_SIDECAR_NAME = "request.json"
_SETTLEMENT_SIDECAR_NAME = "settlement.json"
_OPERATION_REQUEST_NAME = "operation-request.json"
_OPERATION_RESULT_NAME = "operation-result.json"

_LAUNCH_BARRIER_TIMEOUT_SECONDS = 30.0
_START_ACK_TIMEOUT_SECONDS = 20.0
_LAUNCH_BARRIER_TIMEOUT_ENV = "SASE_PROC_LAUNCH_BARRIER_TIMEOUT_SECONDS"
_START_ACK_TIMEOUT_ENV = "SASE_PROC_START_ACK_TIMEOUT_SECONDS"


def proc_runtime_dir(proc_id: str) -> Path:
    """Return ``~/.sase/procs/runtime/<proc_id>``."""
    return procs_dir() / "runtime" / proc_id


def proc_go_path(proc_id: str) -> Path:
    return proc_runtime_dir(proc_id) / _PROC_GO_MARKER


def proc_started_path(proc_id: str) -> Path:
    return proc_runtime_dir(proc_id) / _PROC_STARTED_MARKER


def proc_request_sidecar_path(proc_id: str) -> Path:
    return proc_runtime_dir(proc_id) / _REQUEST_SIDECAR_NAME


def proc_settlement_sidecar_path(proc_id: str) -> Path:
    return proc_runtime_dir(proc_id) / _SETTLEMENT_SIDECAR_NAME


def proc_operation_request_path(proc_id: str) -> Path:
    return proc_runtime_dir(proc_id) / _OPERATION_REQUEST_NAME


def proc_operation_result_path(proc_id: str) -> Path:
    return proc_runtime_dir(proc_id) / _OPERATION_RESULT_NAME


def launch_barrier_timeout_seconds() -> float:
    return _env_seconds(_LAUNCH_BARRIER_TIMEOUT_ENV, _LAUNCH_BARRIER_TIMEOUT_SECONDS)


def start_ack_timeout_seconds() -> float:
    return _env_seconds(_START_ACK_TIMEOUT_ENV, _START_ACK_TIMEOUT_SECONDS)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write *payload* so a reader never observes a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def read_json_object(path: Path) -> dict[str, Any]:
    """Return a JSON object from *path*, or ``{}`` when missing/invalid."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _env_seconds(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(0.05, float(raw))
    except ValueError:
        return default


__all__ = [
    "launch_barrier_timeout_seconds",
    "proc_go_path",
    "proc_operation_request_path",
    "proc_operation_result_path",
    "proc_request_sidecar_path",
    "proc_runtime_dir",
    "proc_settlement_sidecar_path",
    "proc_started_path",
    "read_json_object",
    "start_ack_timeout_seconds",
    "write_json_atomic",
]
