"""Worktree patch creation for workspace rescue."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from sase.workspace_provider._rescue_git_commands import RESCUE_GIT_TIMEOUT_SECONDS

RESCUE_PATCH_NAME = "worktree.patch"

#: Cap for the worktree patch (64 MiB). Larger worktrees skip the patch and
#: record a note in the manifest instead.
RESCUE_PATCH_MAX_BYTES = 64 * 1024 * 1024

_EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def write_worktree_patch(
    repo_root: Path, rescue_dir: Path, head_sha: str | None
) -> tuple[Path | None, str | None]:
    patch_path = rescue_dir / RESCUE_PATCH_NAME
    tmp_index = rescue_dir / ".tmp-rescue-index"
    try:
        from sase.workspace_provider._utils_git import non_interactive_git_env

        env = non_interactive_git_env()
        env["GIT_INDEX_FILE"] = str(tmp_index)
        try:
            add = subprocess.run(
                ["git", "add", "-A"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
                env=env,
                stdin=subprocess.DEVNULL,
                timeout=RESCUE_GIT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"worktree patch skipped: git add failed: {exc}"
        if add.returncode != 0:
            return None, (
                "worktree patch skipped: "
                f"{(add.stderr or add.stdout or '').strip() or 'git add failed'}"
            )
        base = head_sha or _EMPTY_TREE_SHA
        try:
            diff = subprocess.run(
                ["git", "diff", "--cached", "--binary", base],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
                env=env,
                stdin=subprocess.DEVNULL,
                timeout=RESCUE_GIT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"worktree patch skipped: git diff failed: {exc}"
        if diff.returncode != 0:
            return None, (
                "worktree patch skipped: "
                f"{(diff.stderr or diff.stdout or '').strip() or 'git diff failed'}"
            )
        content = diff.stdout or ""
        if not content.strip():
            return None, None
        if len(content.encode("utf-8")) > RESCUE_PATCH_MAX_BYTES:
            return None, (
                f"worktree patch skipped: {len(content.encode('utf-8'))} bytes "
                f"exceeds the {RESCUE_PATCH_MAX_BYTES}-byte cap"
            )
        patch_path.write_text(content, encoding="utf-8")
        return patch_path, None
    finally:
        try:
            tmp_index.unlink(missing_ok=True)
        except OSError:
            pass
