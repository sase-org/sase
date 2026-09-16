"""Best-effort worktree snapshots for unlaunchable monitor follow-ups."""

from __future__ import annotations

import subprocess
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from sase.axe.run_agent_helpers_artifacts import update_meta_field

WORKTREE_RECOVERY_DIFF_FIELD = "monitor_worktree_recovery_diff_path"
WORKTREE_RECOVERY_DIFF_LOCATOR = "diagnostics/worktree_recovery.diff"

_GIT_TIMEOUT_SECONDS = 10


def snapshot_worktree_recovery_diff(
    artifacts_dir: str,
    meta: MutableMapping[str, Any],
) -> str | None:
    """Snapshot the monitored git worktree's dirty state, if any.

    Recovery evidence must never hide the original monitor-follow-up failure,
    so every probe in this helper degrades to ``None`` on error.
    """
    existing = _clean_str(meta.get(WORKTREE_RECOVERY_DIFF_FIELD))
    if existing and Path(existing).is_file():
        return existing

    cwd = _clean_str(meta.get("monitor_cwd"))
    if cwd is None:
        return None
    workspace = Path(cwd).expanduser()
    if not workspace.is_dir():
        return None

    root = _git_root(workspace)
    if root is None:
        return None
    diff_text = _worktree_diff(root)
    if not diff_text or not diff_text.strip():
        return None

    snapshot_path = Path(artifacts_dir) / WORKTREE_RECOVERY_DIFF_LOCATOR
    try:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(diff_text, encoding="utf-8")
    except OSError:
        return None

    value = str(snapshot_path)
    meta[WORKTREE_RECOVERY_DIFF_FIELD] = value
    update_meta_field(artifacts_dir, WORKTREE_RECOVERY_DIFF_FIELD, value)
    return value


def append_worktree_recovery_hint(prompt: str, snapshot_path: str | None) -> str:
    """Add a recovery diff pointer to an unlaunchable follow-up prompt."""
    if not snapshot_path:
        return prompt
    hint = (
        "\n\n## Worktree recovery diff\n\n"
        "The monitored workspace had uncommitted changes when auto-dispatch "
        "failed. A best-effort recovery diff was saved here:\n\n"
        f"```text\n{snapshot_path}\n```\n"
    )
    marker = "%xprompts_enabled:true"
    stripped = prompt.rstrip()
    if stripped.endswith(marker):
        prefix = stripped[: -len(marker)].rstrip()
        return f"{prefix}{hint}\n{marker}"
    return f"{stripped}{hint}"


def _git_root(cwd: Path) -> Path | None:
    result = _run_git(["rev-parse", "--show-toplevel"], cwd)
    if result is None or result.returncode != 0:
        return None
    root = result.stdout.strip()
    return Path(root) if root else None


def _worktree_diff(root: Path) -> str | None:
    tracked = _run_git(["diff", "HEAD"], root)
    untracked = _run_git(["ls-files", "--others", "--exclude-standard", "-z"], root)
    if tracked is None or untracked is None:
        return None
    if tracked.returncode != 0 or untracked.returncode != 0:
        return None

    parts = [tracked.stdout]
    for path in (item for item in untracked.stdout.split("\0") if item):
        diff = _run_git(["diff", "--no-index", "--", "/dev/null", path], root)
        if diff is None:
            continue
        if diff.stdout:
            parts.append(diff.stdout)
    combined = "".join(parts)
    return combined if combined.strip() else None


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _clean_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


__all__ = [
    "WORKTREE_RECOVERY_DIFF_FIELD",
    "WORKTREE_RECOVERY_DIFF_LOCATOR",
    "append_worktree_recovery_hint",
    "snapshot_worktree_recovery_diff",
]
