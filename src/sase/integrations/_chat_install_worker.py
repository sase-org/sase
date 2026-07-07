"""Reusable worker-side helpers for chat install/update jobs."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.time import local_now

from ._chat_install_models import ChatInstallConfig


@dataclass(frozen=True)
class UpdateCommandResult:
    exit_code: int
    message: str


def run_update_command(
    config: ChatInstallConfig,
    *,
    run: Callable[..., Any],
    log: Callable[[str], None],
    log_block: Callable[[str, str | bytes], None],
) -> UpdateCommandResult:
    argv = [sys.executable, "-m", "sase", "update", "--json"]
    log(f"running update command: {shlex.join(argv)}")
    try:
        completed = run(
            argv,
            text=True,
            capture_output=True,
            timeout=config.timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        log(f"update command timed out after {config.timeout_seconds}s")
        if exc.stdout:
            log_block("stdout", exc.stdout)
        if exc.stderr:
            log_block("stderr", exc.stderr)
        return UpdateCommandResult(
            exit_code=124,
            message="Update failed with exit code 124.",
        )

    if completed.stdout:
        log_block("stdout", completed.stdout)
    if completed.stderr:
        log_block("stderr", completed.stderr)
    log(f"update command exit code: {completed.returncode}")
    return UpdateCommandResult(
        exit_code=completed.returncode,
        message=_completion_message(completed.returncode, completed.stdout),
    )


def _completion_message(exit_code: int, stdout: object) -> str:
    if isinstance(stdout, bytes):
        stdout = stdout.decode(errors="replace")
    parsed = _completion_message_from_update_json(
        exit_code, stdout if isinstance(stdout, str) else ""
    )
    if parsed is not None:
        return parsed
    return (
        "Update completed successfully."
        if exit_code == 0
        else f"Update failed with exit code {exit_code}."
    )


def _completion_message_from_update_json(exit_code: int, stdout: str) -> str | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    error = payload.get("error")
    if isinstance(error, str) and error:
        return f"Update failed: {error}"

    if exit_code != 0:
        failed = _failed_package_summary(payload)
        if failed is not None:
            return f"Update failed: {failed}"
        return None

    changed = payload.get("changed")
    if changed is False:
        return "Already up to date."
    if changed is not True:
        return None

    summary = _changed_package_summary(payload)
    return f"Update completed: {summary}." if summary else "Update completed."


def _changed_package_summary(payload: dict[str, Any]) -> str:
    updated = _updated_packages(payload)
    parts: list[str] = []

    sase = next(
        (
            package
            for package in updated
            if _string_value(package.get("name")) == "sase"
        ),
        None,
    )
    if sase is not None:
        parts.append(_package_version_summary(sase))

    core = next(
        (
            package
            for package in updated
            if package is not sase and _is_core_package(package)
        ),
        None,
    )
    if core is not None:
        parts.append(_core_version_summary(core))

    plugin_count = sum(
        1
        for package in updated
        if package is not sase
        and package is not core
        and _string_value(package.get("role")) == "plugin"
        and _string_value(package.get("name")) != "sase"
    )
    if plugin_count:
        parts.append(f"{plugin_count} {_plural(plugin_count, 'plugin')} updated")

    other_count = (
        len(updated)
        - (1 if sase is not None else 0)
        - (1 if core is not None else 0)
        - plugin_count
    )
    if other_count:
        parts.append(f"{other_count} {_plural(other_count, 'package')} updated")

    if parts:
        return ", ".join(parts)

    counts = payload.get("counts")
    if isinstance(counts, dict):
        updated_count = _int_value(counts.get("updated"))
        removed_count = _int_value(counts.get("removed"))
        if updated_count:
            return f"{updated_count} {_plural(updated_count, 'package')} updated"
        if removed_count:
            return f"{removed_count} {_plural(removed_count, 'package')} removed"
    return "changes applied"


def _is_core_package(package: dict[str, Any]) -> bool:
    return (
        _string_value(package.get("role")) == "core"
        or _string_value(package.get("name")) == "sase-core-rs"
    )


def _core_version_summary(package: dict[str, Any]) -> str:
    old_version = _string_value(package.get("old_version"))
    new_version = _string_value(package.get("new_version"))
    if old_version and new_version:
        return f"core {old_version} to {new_version}"
    if new_version:
        return f"core updated to {new_version}"
    return "core updated"


def _updated_packages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    packages = payload.get("packages")
    if not isinstance(packages, list):
        return []
    return [
        package
        for package in packages
        if isinstance(package, dict)
        and (
            package.get("kind") in {"added", "upgraded"}
            or package.get("status") == "updated"
        )
    ]


def _failed_package_summary(payload: dict[str, Any]) -> str | None:
    packages = payload.get("packages")
    if not isinstance(packages, list):
        return None
    for package in packages:
        if not isinstance(package, dict) or package.get("status") != "failed":
            continue
        name = _string_value(package.get("name")) or "package"
        reason = _string_value(package.get("reason"))
        return f"{name}: {reason}" if reason else f"{name} failed"
    return None


def _package_version_summary(package: dict[str, Any]) -> str:
    name = _string_value(package.get("name")) or "sase"
    old_version = _string_value(package.get("old_version"))
    new_version = _string_value(package.get("new_version"))
    if old_version and new_version:
        return f"{name} {old_version} to {new_version}"
    if new_version:
        return f"{name} updated to {new_version}"
    return f"{name} updated"


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_value(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _plural(count: int, singular: str) -> str:
    return singular if count == 1 else f"{singular}s"


def restart_axe(
    attempts: int,
    *,
    start: Callable[[], int | None],
    is_running: Callable[[], bool],
    sleep: Callable[[float], None],
    log: Callable[[str], None],
) -> bool:
    for attempt in range(1, attempts + 1):
        log(f"starting axe (attempt {attempt}/{attempts})")
        try:
            pid = start()
        except Exception as exc:
            log(f"start axe attempt failed: {type(exc).__name__}: {exc}")
            pid = None
        if pid is not None and is_running():
            log(f"axe restart succeeded: pid {pid}")
            return True
        sleep(min(attempt, 5))
    log("axe restart failed after all attempts")
    return False


def write_completion_record(
    status_path: Path,
    *,
    job_id: str | None,
    exit_code: int,
    log_path: Path | None,
    workspace: Path | None,
    started_at: str,
    completed_at: str,
    restart_succeeded: bool | None,
    message: str,
) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "job_id": job_id,
        "status": "success" if exit_code == 0 else "failed",
        "exit_code": exit_code,
        "log_path": str(log_path) if log_path is not None else None,
        "workspace": str(workspace) if workspace is not None else None,
        "started_at": started_at,
        "completed_at": completed_at,
        "restart_succeeded": restart_succeeded,
        "message": message,
    }
    temp_path = status_path.with_name(f".{status_path.name}.{os.getpid()}.tmp")
    temp_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    temp_path.replace(status_path)


def log_message(message: str) -> None:
    timestamp = local_now().isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", flush=True)


def log_block(
    label: str,
    text: str | bytes,
    *,
    log: Callable[[str], None] = log_message,
) -> None:
    if isinstance(text, bytes):
        text = text.decode(errors="replace")
    log(f"{label}:")
    print(text.rstrip(), flush=True)
