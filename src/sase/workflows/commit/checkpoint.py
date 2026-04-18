"""Checkpoint persistence for resumable commit workflows."""

from __future__ import annotations

import dataclasses
import json
import os
import time
from dataclasses import dataclass, field

from sase.output import print_status

_CHECKPOINT_VERSION = 1
_CHECKPOINT_FILENAME = "commit_state.json"


@dataclass
class _CommitCheckpoint:
    """Snapshot of a `CommitWorkflow` invocation, persisted between attempts."""

    method: str
    payload: dict
    cwd: str
    version: int = _CHECKPOINT_VERSION
    cl_name: str | None = None
    project_file: str | None = None
    diff_path: str | None = None
    base_cl_name: str | None = None
    reserved_name: str | None = None
    parent_cl_name: str | None = None
    dispatch_result: str | None = None
    cs_name: str | None = None
    entry_id: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


def get_checkpoint_path() -> str:
    """Return the on-disk path used for checkpoint persistence.

    Prefers ``$SASE_ARTIFACTS_DIR/commit_state.json`` when the env var is set,
    otherwise falls back to a per-session file under ``~/.sase/commit_state/``.
    """
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if artifacts_dir:
        path = os.path.join(artifacts_dir, _CHECKPOINT_FILENAME)
    else:
        session_id = os.environ.get("SASE_AGENT_TIMESTAMP") or str(os.getpid())
        path = os.path.expanduser(f"~/.sase/commit_state/{session_id}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def save(cp: _CommitCheckpoint, path: str | None = None) -> str | None:
    """Atomically persist *cp* to *path*; return the path written, or None on failure."""
    target = path or get_checkpoint_path()
    tmp = target + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(dataclasses.asdict(cp), f)
        os.replace(tmp, target)
    except OSError as exc:
        print_status(f"Failed to write commit checkpoint to {target}: {exc}", "warning")
        return None
    return target


def load(path: str | None = None) -> _CommitCheckpoint | None:
    """Read a checkpoint from *path*; return None if missing, malformed, or unknown version."""
    target = path or get_checkpoint_path()
    try:
        with open(target) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    version = data.get("version")
    if version != _CHECKPOINT_VERSION:
        print_status(
            f"Refusing to load commit checkpoint at {target}: "
            f"unknown version {version!r} (expected {_CHECKPOINT_VERSION})",
            "warning",
        )
        return None
    try:
        return _CommitCheckpoint(**data)
    except TypeError:
        return None


def delete(path: str | None = None) -> None:
    """Best-effort removal of the checkpoint file at *path*."""
    target = path or get_checkpoint_path()
    try:
        os.remove(target)
    except FileNotFoundError:
        pass
