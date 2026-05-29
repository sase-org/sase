"""Doctor and repair helpers for the automatic episode builder."""

from __future__ import annotations

import fcntl
from pathlib import Path
import shutil
from typing import Any

from sase.memory.episodes._auto_build_locks import (
    release_episode_lock,
    try_acquire_episode_lock,
)
from sase.memory.episodes._auto_build_state import (
    fsync_dir,
    read_build_state_details_unlocked,
    write_build_state_unlocked,
)
from sase.memory.episodes._auto_build_types import (
    EpisodeAutoBuildStateRecord,
    EpisodeDoctorReport,
)
from sase.memory.episodes.index import (
    episode_index_lock_path,
    episode_index_path,
    project_episodes_dir,
    read_episode_index_unlocked,
)


def build_episode_auto_doctor_report(
    project: str,
    *,
    projects_root: Path | str | None = None,
    repair: bool = False,
) -> EpisodeDoctorReport:
    """Inspect and optionally repair automatic episode builder state."""

    episodes_dir = project_episodes_dir(project, projects_root=projects_root)
    index_path = episode_index_path(project, projects_root=projects_root)
    held = try_acquire_episode_lock(episode_index_lock_path(index_path), fcntl.LOCK_EX)
    if held is None:
        return EpisodeDoctorReport(
            project=project,
            episodes_dir=str(episodes_dir.resolve(strict=False)),
            status="ERROR",
            checks=[
                _doctor_check(
                    "lock",
                    "ERROR",
                    "Episode index lock is held by another writer.",
                )
            ],
            repairs=[],
            repaired=False,
            lock_acquired=False,
        )
    try:
        checks: list[dict[str, Any]] = []
        repairs: list[dict[str, Any]] = []
        state_status, state, state_error = read_build_state_details_unlocked(
            episodes_dir,
            project,
        )
        prev_status, prev_state, prev_error = read_build_state_details_unlocked(
            episodes_dir,
            project,
            previous=True,
        )
        checks.append(
            _state_doctor_check(
                state_status,
                state,
                state_error,
                prev_status=prev_status,
                prev_error=prev_error,
            )
        )
        checks.append(
            _doctor_check(
                "build_state_prev",
                "OK" if prev_status in {"ok", "missing"} else "WARN",
                _prev_state_summary(prev_status, prev_error),
            )
        )
        index_rows = read_episode_index_unlocked(index_path)
        checks.append(
            _doctor_check(
                "index",
                "OK",
                f"Episode index has {len(index_rows)} row(s).",
            )
        )
        temp_dirs = _storage_temp_dirs(episodes_dir)
        if temp_dirs:
            repairs.append(
                _repair_plan(
                    "remove_temp_dirs",
                    f"Remove {len(temp_dirs)} abandoned episode temp dir(s).",
                )
            )
            checks.append(
                _doctor_check(
                    "temp_dirs",
                    "WARN",
                    f"Found {len(temp_dirs)} abandoned episode temp dir(s).",
                    details=[str(path) for path in temp_dirs],
                )
            )
        else:
            checks.append(
                _doctor_check("temp_dirs", "OK", "No abandoned temp dirs found.")
            )
        if state_status == "corrupt" and prev_status == "ok" and prev_state is not None:
            repairs.append(
                _repair_plan(
                    "restore_build_state_prev",
                    "Restore build_state.json from build_state.json.prev.",
                )
            )

        executed_repairs = False
        if repair:
            executed_repairs = _execute_repairs(
                episodes_dir,
                project,
                repairs=repairs,
                prev_state=prev_state,
                temp_dirs=temp_dirs,
            )
            repairs = [dict(item, executed=True) for item in repairs]
        aggregate = _aggregate_doctor_status(checks)
        return EpisodeDoctorReport(
            project=project,
            episodes_dir=str(episodes_dir.resolve(strict=False)),
            status=aggregate,
            checks=checks,
            repairs=repairs,
            repaired=executed_repairs,
            lock_acquired=True,
        )
    finally:
        release_episode_lock(held)


def _storage_temp_dirs(episodes_dir: Path) -> list[Path]:
    if not episodes_dir.exists():
        return []
    return [
        path
        for path in sorted(episodes_dir.iterdir(), key=lambda item: item.name)
        if path.is_dir() and path.name.startswith(".") and ".tmp." in path.name
    ]


def _execute_repairs(
    episodes_dir: Path,
    project: str,
    *,
    repairs: list[dict[str, Any]],
    prev_state: EpisodeAutoBuildStateRecord | None,
    temp_dirs: list[Path],
) -> bool:
    executed = False
    repair_ids = {repair["id"] for repair in repairs}
    if "restore_build_state_prev" in repair_ids and prev_state is not None:
        write_build_state_unlocked(episodes_dir, prev_state)
        executed = True
    if "remove_temp_dirs" in repair_ids:
        for path in temp_dirs:
            shutil.rmtree(path, ignore_errors=True)
        fsync_dir(episodes_dir)
        executed = True
    del project
    return executed


def _state_doctor_check(
    status: str,
    state: EpisodeAutoBuildStateRecord | None,
    error: str | None,
    *,
    prev_status: str,
    prev_error: str | None,
) -> dict[str, Any]:
    if status == "ok" and state is not None:
        return _doctor_check(
            "build_state",
            "OK",
            "build_state.json is valid.",
            details=[
                f"checkpoint={state.checkpoint_timestamp or '-'}",
                f"consecutive_failures={state.consecutive_failures}",
            ],
        )
    if status == "missing":
        return _doctor_check(
            "build_state",
            "OK",
            "build_state.json is not present yet.",
        )
    if prev_status == "ok":
        return _doctor_check(
            "build_state",
            "WARN",
            "build_state.json is corrupt but build_state.json.prev is valid.",
            details=[error or "invalid state"],
        )
    detail = error or prev_error or "invalid state"
    return _doctor_check(
        "build_state",
        "ERROR",
        "build_state.json is corrupt and no valid previous state is available.",
        details=[detail],
    )


def _prev_state_summary(status: str, error: str | None) -> str:
    if status == "ok":
        return "build_state.json.prev is valid."
    if status == "missing":
        return "build_state.json.prev is not present."
    return f"build_state.json.prev is corrupt: {error or 'invalid state'}"


def _doctor_check(
    check_id: str,
    status: str,
    summary: str,
    *,
    details: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "summary": summary,
        "details": details or [],
    }


def _repair_plan(repair_id: str, summary: str) -> dict[str, Any]:
    return {"id": repair_id, "summary": summary, "executed": False}


def _aggregate_doctor_status(checks: list[dict[str, Any]]) -> str:
    statuses = {str(check.get("status")) for check in checks}
    if "ERROR" in statuses:
        return "ERROR"
    if "WARN" in statuses:
        return "WARN"
    return "OK"
