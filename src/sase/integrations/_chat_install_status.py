"""Status decoding for chat install/update jobs."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from ._chat_install_models import ChatInstallStatusResult, JobStatus


def read_chat_install_status(
    job_id: str,
    *,
    valid_job_id: Callable[[str], bool],
    completion_path_for: Callable[[str], Path],
    read_job_state: Callable[[str], dict[str, object] | None],
    lock_is_held: Callable[[], bool],
) -> ChatInstallStatusResult:
    """Read structured status for a chat install/update job."""
    if not valid_job_id(job_id):
        return ChatInstallStatusResult(
            status="not_found",
            message="Update job was not found.",
            job_id=job_id,
        )

    completion_path = completion_path_for(job_id)
    if completion_path.is_file():
        return _read_completion_status(job_id, completion_path)

    state = read_job_state(job_id)
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
            completion_path=state_completion or completion_path,
            workspace=workspace,
        )

    if state.get("status") == "failed":
        return ChatInstallStatusResult(
            status="failed",
            message=_string_or_default(state.get("message"), "Update failed."),
            job_id=job_id,
            started_at=_optional_string_value(state.get("started_at")),
            finished_at=_optional_string_value(state.get("finished_at")),
            log_path=log_path,
            completion_path=state_completion or completion_path,
            workspace=workspace,
        )

    return ChatInstallStatusResult(
        status="failed",
        message="Update job ended before writing a completion record.",
        job_id=job_id,
        started_at=_optional_string_value(state.get("started_at")),
        finished_at=_optional_string_value(state.get("finished_at")),
        log_path=log_path,
        completion_path=state_completion or completion_path,
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


def _optional_path(value: object) -> Path | None:
    return Path(value) if isinstance(value, str) and value else None


def _optional_string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_or_default(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
