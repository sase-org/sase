"""Shared kernel for the managed bead sync worker.

Public helpers live in this already-private module so the focused worker
modules can share them without importing ``_``-prefixed names from each other.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import subprocess
import time
from pathlib import Path
from typing import Any


def log_sync_event(log_path: Path, event: str, **fields: Any) -> None:
    record = {"ts": time.time(), "event": event, **fields}
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record, sort_keys=True) + "\n")


def resolve_git_dir(repo_root: Path) -> Path:
    # This read-only probe cannot contend on the repository index.
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    path = Path(result.stdout.strip()) if result.returncode == 0 else Path(".git")
    return path if path.is_absolute() else repo_root / path


def rev_parse_head(
    repo_root: Path,
    git_runner: Callable[..., subprocess.CompletedProcess[str]],
    *,
    op: str,
) -> str | None:
    """Resolve HEAD without raising; None when it cannot be read."""
    try:
        result = git_runner(repo_root, ["rev-parse", "--verify", "HEAD"], op=op)
    except Exception:  # noqa: BLE001 - a missing HEAD only skips the rollback
        return None
    head = result.stdout.strip() if result.returncode == 0 else ""
    return head or None


def deadline_remaining(deadline: float | None) -> float:
    if deadline is None:
        return 0.0
    return max(0.0, deadline - time.monotonic())


def deadline_timeout(
    deadline: float | None,
    cap: float | None = None,
) -> float | None:
    if deadline is None:
        return cap
    remaining = max(0.001, deadline_remaining(deadline))
    return remaining if cap is None else min(cap, remaining)
