"""Durable markers and rate limits for SDD repository recovery."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any

from sase.sdd._repository_transaction import (
    GitRunner,
    LockFactory,
    SddIntegrationOutcome,
    default_git_runner,
)

RECOVERY_ATTEMPT_MARKER = "sase-sdd-recovery-attempt.json"
_RECOVERY_WARNING_MARKER = "sase-sdd-recovery-warning.json"
_RECOVERY_REPORT_MARKER = "sase-sdd-recovery-report.json"
_WARNING_COOLDOWN_SECONDS = 900.0
_REPORT_COOLDOWN_SECONDS = 3600.0


def recovery_failure_signature(
    repo_root: Path,
    outcome: SddIntegrationOutcome,
) -> str:
    """Return a stable clone-and-failure identity for durable rate limits."""
    root = repo_root.expanduser().resolve()
    detail = outcome.error or outcome.status.value
    payload = f"{root}\0{outcome.status.value}\0{detail}".encode(
        "utf-8", errors="replace"
    )
    return hashlib.sha256(payload).hexdigest()


def admit_recovery_notice(
    repo_root: Path,
    signature: str,
    *,
    report: bool = False,
    git_runner: GitRunner | None = None,
    lock_factory: LockFactory | None = None,
    clock: Callable[[], float] | None = None,
) -> bool:
    """Durably admit one warning or axe report for a failure signature."""
    root = repo_root.expanduser().resolve()
    runner = git_runner or default_git_runner
    if lock_factory is None:
        from sase.sdd._git_contention import store_git_write_lock

        lock_factory = store_git_write_lock
    now = (clock or time.time)()
    marker_name = _RECOVERY_REPORT_MARKER if report else _RECOVERY_WARNING_MARKER
    cooldown = _REPORT_COOLDOWN_SECONDS if report else _WARNING_COOLDOWN_SECONDS

    with lock_factory(root) as acquired:
        if not acquired:
            return False
        git_dir = _repository_git_dir(root, runner, op="sdd.recovery.notice")
        if git_dir is None:
            return False
        marker = git_dir / marker_name
        record = read_recovery_marker(marker)
        if record.get("signature") == signature and timestamp_is_recent(
            record.get("timestamp"), now, cooldown
        ):
            return False
        return write_recovery_marker(
            marker,
            {
                "clone_path": str(root),
                "signature": signature,
                "timestamp": now,
            },
        )


def _repository_git_dir(
    repo_root: Path,
    runner: GitRunner,
    *,
    op: str,
) -> Path | None:
    result = runner(repo_root, ["rev-parse", "--git-dir"], op=op)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    git_dir = Path(result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = repo_root / git_dir
    return git_dir


def read_recovery_marker(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def write_recovery_marker(path: Path, value: dict[str, Any]) -> bool:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def timestamp_is_recent(
    raw_timestamp: Any,
    now: float,
    cooldown_seconds: float,
) -> bool:
    try:
        timestamp = float(raw_timestamp)
    except (TypeError, ValueError):
        return False
    age = now - timestamp
    return age < cooldown_seconds if age >= 0 else True
