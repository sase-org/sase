"""JSON state persistence for chat install/update jobs."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path


def read_job_state(
    job_id: str,
    *,
    job_state_path_for: Callable[[str], Path],
    completion_path_for: Callable[[str], Path],
) -> dict[str, object] | None:
    path = job_state_path_for(job_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _malformed_job_state(job_id, completion_path_for)
    if not isinstance(raw, dict):
        return _malformed_job_state(job_id, completion_path_for)
    return raw


def _malformed_job_state(
    job_id: str, completion_path_for: Callable[[str], Path]
) -> dict[str, object]:
    return {
        "status": "failed",
        "message": "Update job state is malformed.",
        "status_path": str(completion_path_for(job_id)),
    }


def write_job_state(
    job_id: str,
    *,
    status: str,
    message: str,
    log_path: Path | None,
    workspace: Path | None,
    status_path: Path | None,
    pid: int | None,
    started_at: str,
    finished_at: str | None,
    job_state_path_for: Callable[[str], Path],
    process_id: int,
) -> None:
    path = job_state_path_for(job_id)
    record = {
        "job_id": job_id,
        "status": status,
        "message": message,
        "log_path": str(log_path) if log_path is not None else None,
        "workspace": str(workspace) if workspace is not None else None,
        "status_path": str(status_path) if status_path is not None else None,
        "pid": pid,
        "started_at": started_at,
        "finished_at": finished_at,
    }
    temp_path = path.with_name(f".{path.name}.{process_id}.tmp")
    temp_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)
