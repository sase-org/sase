"""Idempotent executor for detached file-hook batches."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import time
from typing import Any
from uuid import uuid4

from sase.core.paths import sase_subdir
from sase.core.time import get_timezone
from sase.file_hooks.engine import BATCH_SCHEMA_VERSION
from sase.notifications.models import Notification
from sase.notifications.store import append_notification

_RETENTION_SECONDS = 30 * 24 * 60 * 60


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temp_path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temp_path, path)


def _load_batch(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError("file-hook batch must be a JSON object")
    if payload.get("schema_version") != BATCH_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported file-hook batch schema {payload.get('schema_version')!r}"
        )
    if not isinstance(payload.get("runs"), list):
        raise ValueError("file-hook batch has no runs list")
    return payload


def _pid_is_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def _claim_batch(path: Path) -> dict[str, Any] | None:
    lock_path = path.with_suffix(f"{path.suffix}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        payload = _load_batch(path)
        if payload.get("status") == "finished":
            return None
        if payload.get("status") == "running" and _pid_is_alive(
            payload.get("runner_pid")
        ):
            return None
        payload["status"] = "running"
        payload["runner_pid"] = os.getpid()
        payload.setdefault("started_at", _now_iso())
        _atomic_write_json(path, payload)
        return payload


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(get_timezone()).isoformat()


def _run_log_path(batch_id: str, index: int, hook_name: str) -> Path:
    safe_hook = "".join(
        char if char.isalnum() or char in "-_" else "_" for char in hook_name
    )
    path = sase_subdir("file_hooks") / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{batch_id}-{index:04d}-{safe_hook}.log"


def _write_run_log(
    path: Path,
    *,
    command_line: str,
    cwd: str,
    output: str,
    outcome: str,
) -> None:
    path.write_text(
        "\n".join(
            [
                f"command: {command_line}",
                f"cwd: {cwd}",
                f"outcome: {outcome}",
                "",
                output,
            ]
        ),
        encoding="utf-8",
    )


def _notify_run(
    run: dict[str, Any],
    *,
    command_line: str,
    duration_seconds: float,
    exit_code: int | None,
    failure: str | None,
    log_path: Path,
) -> None:
    hook_name = str(run["hook_name"])
    basename = Path(str(run["rel_path"])).name
    failed = failure is not None or exit_code not in (0,)
    notes = [
        (
            f"❌ {hook_name} failed: {basename}"
            if failed
            else f"✅ {hook_name}: {basename}"
        ),
        f"hook: {hook_name}",
        f"command: {command_line}",
        f"file: {run['rel_path']}",
        f"operation: {run['op']}",
        f"project: {run['project']}",
        f"repository: {run['repo_kind']}",
        f"duration: {duration_seconds:.3f}s",
        f"exit code: {exit_code if exit_code is not None else failure}",
    ]
    notification = Notification(
        id=str(uuid4()),
        timestamp=_now_iso(),
        sender="file-hooks",
        icon="❌" if failed else "✅",
        notes=notes,
        files=[str(log_path)],
        tags=["file-hooks", hook_name],
        action="ViewErrorReport" if failed else None,
        action_data=({"error_report_path": str(log_path)} if failed else {}),
    )
    append_notification(notification)


def _execute_run(batch_id: str, run: dict[str, Any]) -> dict[str, Any]:
    index = int(run["index"])
    hook_name = str(run["hook_name"])
    command_line = f"{run['command']} {shlex.quote(str(run['abs_path']))}"
    log_path = _run_log_path(batch_id, index, hook_name)
    started = time.monotonic()
    exit_code: int | None = None
    failure: str | None = None
    output = ""
    try:
        process = subprocess.Popen(
            command_line,
            shell=True,
            cwd=str(run["repo_root"]),
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, _stderr = process.communicate(timeout=float(run["timeout_seconds"]))
        except subprocess.TimeoutExpired:
            failure = f"timeout after {run['timeout_seconds']}s"
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                process.kill()
            stdout, _stderr = process.communicate()
        output = stdout or ""
        exit_code = process.returncode
        if exit_code != 0:
            failure = failure or f"exit {exit_code}"
    except Exception as exc:
        failure = f"spawn error: {exc}"
        output = f"{type(exc).__name__}: {exc}\n"

    duration = time.monotonic() - started
    _write_run_log(
        log_path,
        command_line=command_line,
        cwd=str(run["repo_root"]),
        output=output,
        outcome=failure or "success",
    )
    _notify_run(
        run,
        command_line=command_line,
        duration_seconds=duration,
        exit_code=exit_code,
        failure=failure,
        log_path=log_path,
    )
    return {
        **run,
        "status": "finished",
        "finished_at": _now_iso(),
        "duration_seconds": duration,
        "exit_code": exit_code,
        "failure": failure,
        "log_path": str(log_path),
    }


def _prune_file_hook_state(
    *,
    now: float | None = None,
    retention_seconds: float = _RETENTION_SECONDS,
) -> list[Path]:
    """Remove audit files older than the retention window."""
    cutoff = (time.time() if now is None else now) - retention_seconds
    removed: list[Path] = []
    root = sase_subdir("file_hooks")
    for dirname in ("batches", "logs", "runs"):
        directory = root / dirname
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed.append(path)
            except OSError:
                continue
    return removed


def execute_batch(batch_path: str | Path) -> int:
    """Run every unfinished entry in a claimed batch exactly once per state."""
    path = Path(batch_path).expanduser().resolve()
    try:
        _prune_file_hook_state()
        payload = _claim_batch(path)
    except Exception as exc:
        print(f"file-hook batch error: {exc}")
        return 1
    if payload is None:
        return 0

    batch_id = str(payload["batch_id"])
    runs = payload["runs"]
    for index, raw_run in enumerate(runs):
        if not isinstance(raw_run, dict):
            continue
        if raw_run.get("status") == "finished":
            continue
        try:
            finished_run = _execute_run(batch_id, raw_run)
        except Exception as exc:
            finished_run = {
                **raw_run,
                "status": "finished",
                "finished_at": _now_iso(),
                "failure": f"runner error: {exc}",
            }
        runs[index] = finished_run
        _atomic_write_json(path, payload)

    payload["status"] = "finished"
    payload["finished_at"] = _now_iso()
    payload.pop("runner_pid", None)
    _atomic_write_json(path, payload)
    return 0


__all__ = ["execute_batch"]
