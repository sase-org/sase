"""Job state and completion records for chat install/update jobs."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ._chat_install_models import ChatInstallStatusResult, JobStatus
from ._chat_install_lock import lock_is_held
from ._chat_install_paths import completion_path, job_state_path, valid_job_id


def read_chat_install_status(job_id: str) -> ChatInstallStatusResult:
    """Read structured status for a chat install/update job."""
    if not valid_job_id(job_id):
        return ChatInstallStatusResult(
            status="not_found",
            message="Update job was not found.",
            job_id=job_id,
        )

    job_completion_path = completion_path(job_id)
    if job_completion_path.is_file():
        return _read_completion_status(job_id, job_completion_path)

    state = _read_job_state(job_id)
    if state is None:
        return ChatInstallStatusResult(
            status="not_found",
            message="Update job was not found.",
            job_id=job_id,
        )

    log_path = _optional_path(state.get("log_path"))
    workspace = _optional_path(state.get("workspace"))
    state_completion = _optional_path(state.get("status_path"))
    if state.get("status") == "running" and lock_is_held():
        return ChatInstallStatusResult(
            status="running",
            message=_string_or_default(state.get("message"), "Update is running."),
            job_id=job_id,
            started_at=_optional_string_value(state.get("started_at")),
            finished_at=None,
            log_path=log_path,
            completion_path=state_completion or job_completion_path,
            workspace=workspace,
        )

    state_status = state.get("status")
    if state_status == "failed":
        return ChatInstallStatusResult(
            status="failed",
            message=_string_or_default(state.get("message"), "Update failed."),
            job_id=job_id,
            started_at=_optional_string_value(state.get("started_at")),
            finished_at=_optional_string_value(state.get("finished_at")),
            log_path=log_path,
            completion_path=state_completion or job_completion_path,
            workspace=workspace,
        )

    return ChatInstallStatusResult(
        status="failed",
        message="Update job ended before writing a completion record.",
        job_id=job_id,
        started_at=_optional_string_value(state.get("started_at")),
        finished_at=_optional_string_value(state.get("finished_at")),
        log_path=log_path,
        completion_path=state_completion or job_completion_path,
        workspace=workspace,
    )


def _read_completion_status(
    job_id: str, completion_path: Path
) -> ChatInstallStatusResult:
    try:
        raw = json.loads(completion_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ChatInstallStatusResult(
            status="failed",
            message=f"Update completion record is malformed: {type(exc).__name__}.",
            job_id=job_id,
            completion_path=completion_path,
        )
    if not isinstance(raw, dict):
        return ChatInstallStatusResult(
            status="failed",
            message="Update completion record is malformed: expected object.",
            job_id=job_id,
            completion_path=completion_path,
        )

    raw_status = raw.get("status")
    status: JobStatus = "succeeded" if raw_status == "success" else "failed"
    return ChatInstallStatusResult(
        status=status,
        message=_string_or_default(
            raw.get("message"),
            "Update completed successfully."
            if status == "succeeded"
            else "Update failed.",
        ),
        job_id=_string_or_default(raw.get("job_id"), job_id),
        started_at=_optional_string_value(raw.get("started_at")),
        finished_at=_optional_string_value(raw.get("completed_at")),
        log_path=_optional_path(raw.get("log_path")),
        completion_path=completion_path,
        workspace=_optional_path(raw.get("workspace")),
        exit_code=_optional_int(raw.get("exit_code")),
        restart_succeeded=(
            raw.get("restart_succeeded")
            if isinstance(raw.get("restart_succeeded"), bool)
            else None
        ),
    )


def _read_job_state(job_id: str) -> dict[str, object] | None:
    path = job_state_path(job_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "failed",
            "message": "Update job state is malformed.",
            "status_path": str(completion_path(job_id)),
        }
    if not isinstance(raw, dict):
        return {
            "status": "failed",
            "message": "Update job state is malformed.",
            "status_path": str(completion_path(job_id)),
        }
    return raw


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
) -> None:
    path = job_state_path(job_id)
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
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _optional_path(value: object) -> Path | None:
    return Path(value) if isinstance(value, str) and value else None


def _optional_string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_or_default(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
