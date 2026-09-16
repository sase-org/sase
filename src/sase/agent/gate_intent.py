"""Durable agent-side intent markers for gate creation."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.process_identity import process_identity_token

logger = logging.getLogger(__name__)

GATE_INTENT_PREFIX = ".sase_gate_intent."
GATE_INTENT_GLOB = f"{GATE_INTENT_PREFIX}*.json"


@dataclass(frozen=True)
class GateIntent:
    """One persisted gate-creation intent marker."""

    path: Path
    payload: dict[str, Any]
    kind: str | None
    request_id: str | None
    source: str | None
    pid: int | None
    process_identity: str | None
    timestamp: float | None
    corrupt: bool = False


def intent_artifacts_dir(env: Mapping[str, str] | None = None) -> str | None:
    """Return the artifacts dir where this process should write intents."""
    current_env = env if env is not None else os.environ
    if not current_env.get("SASE_AGENT"):
        return None
    artifacts_dir = current_env.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return None
    if _is_runner_process(artifacts_dir):
        return None
    return artifacts_dir


def begin_gate_intent(
    kind: str,
    *,
    request_id: str | None = None,
    source: str | None = None,
) -> Path | None:
    """Write or re-stamp this process's gate-creation intent marker."""
    artifacts_dir = intent_artifacts_dir()
    if artifacts_dir is None:
        return None

    pid = os.getpid()
    payload: dict[str, Any] = {
        "kind": kind,
        "request_id": request_id,
        "source": source or "create_gate_shell",
        "pid": pid,
        "process_identity": process_identity_token(pid),
        "timestamp": time.time(),
    }
    path = _marker_path(artifacts_dir, pid)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, payload)
    except OSError:
        logger.debug("could not write gate intent marker %s", path, exc_info=True)
        return None
    return path


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically and fsync before replacing ``path``."""
    fd, temp_path = tempfile.mkstemp(
        dir=path.parent, prefix=f"{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def clear_gate_intent(artifacts_dir: str | None = None) -> None:
    """Remove this process's gate-creation intent marker, if present."""
    resolved = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not resolved:
        return
    try:
        _marker_path(resolved, os.getpid()).unlink()
    except FileNotFoundError:
        return
    except OSError:
        logger.debug("could not clear gate intent marker", exc_info=True)


def gate_intent_paths(artifacts_dir: str | Path) -> list[Path]:
    """Return gate-intent marker paths under ``artifacts_dir``."""
    try:
        return sorted(Path(artifacts_dir).glob(GATE_INTENT_GLOB))
    except OSError:
        return []


def list_gate_intents(artifacts_dir: str | Path | None) -> list[GateIntent]:
    """Return every gate intent marker, tolerating corrupt marker JSON."""
    if not artifacts_dir:
        return []
    intents = [_read_gate_intent(path) for path in gate_intent_paths(artifacts_dir)]
    return sorted(intents, key=_intent_sort_key)


def discard_gate_intents(artifacts_dir: str | Path | None) -> None:
    """Remove every gate intent marker under ``artifacts_dir``."""
    if not artifacts_dir:
        return
    for path in gate_intent_paths(artifacts_dir):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            logger.debug("could not discard gate intent marker %s", path, exc_info=True)


def _is_runner_process(artifacts_dir: str) -> bool:
    try:
        with (Path(artifacts_dir) / "agent_meta.json").open(encoding="utf-8") as stream:
            meta = json.load(stream)
    except (OSError, ValueError):
        return False
    if not isinstance(meta, dict):
        return False
    raw_pid = meta.get("pid")
    if not isinstance(raw_pid, int | str) or isinstance(raw_pid, bool):
        return False
    try:
        runner_pid = int(raw_pid)
    except ValueError:
        return False
    return runner_pid == os.getpid()


def _marker_path(artifacts_dir: str | Path, pid: int) -> Path:
    return Path(artifacts_dir) / f"{GATE_INTENT_PREFIX}{pid}.json"


def _read_gate_intent(path: Path) -> GateIntent:
    corrupt = False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
        corrupt = True
    if not isinstance(data, dict):
        data = {}
        corrupt = True

    kind = data.get("kind") if isinstance(data.get("kind"), str) else None
    request_id = (
        data.get("request_id") if isinstance(data.get("request_id"), str) else None
    )
    source = data.get("source") if isinstance(data.get("source"), str) else None
    pid = _optional_int(data.get("pid"))
    if pid is None:
        pid = _pid_from_marker_name(path)
    process_identity = (
        data.get("process_identity")
        if isinstance(data.get("process_identity"), str)
        else None
    )
    timestamp = _optional_float(data.get("timestamp"))
    if timestamp is None:
        timestamp = _mtime(path)
    return GateIntent(
        path=path,
        payload=dict(data),
        kind=kind,
        request_id=request_id,
        source=source,
        pid=pid,
        process_identity=process_identity,
        timestamp=timestamp,
        corrupt=corrupt,
    )


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _pid_from_marker_name(path: Path) -> int | None:
    name = path.name
    if not name.startswith(GATE_INTENT_PREFIX) or not name.endswith(".json"):
        return None
    return _optional_int(name[len(GATE_INTENT_PREFIX) : -len(".json")])


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _intent_sort_key(intent: GateIntent) -> tuple[float, str]:
    timestamp = intent.timestamp if intent.timestamp is not None else 0.0
    return (timestamp, str(intent.path))


__all__ = [
    "GATE_INTENT_GLOB",
    "GATE_INTENT_PREFIX",
    "GateIntent",
    "atomic_write_json",
    "begin_gate_intent",
    "clear_gate_intent",
    "discard_gate_intents",
    "gate_intent_paths",
    "intent_artifacts_dir",
    "list_gate_intents",
]
