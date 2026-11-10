"""Bound Git discovery before operating on a caller-selected checkout."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


def _toplevel(path: str | Path, *, bounded: bool) -> Path | None:
    target = Path(path).expanduser().resolve()
    env = os.environ.copy()
    if bounded:
        env["GIT_CEILING_DIRECTORIES"] = str(target.parent)
    else:
        env.pop("GIT_CEILING_DIRECTORIES", None)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=target,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve()


def is_worktree_root(path: str | Path) -> bool:
    """Accept clones and Git worktrees, never an enclosing repository."""
    return _toplevel(path, bounded=True) == Path(path).expanduser().resolve()


def is_bare_repository_root(path: str | Path) -> bool:
    """Probe an explicit Git directory, without discovery in its parents."""
    target = Path(path).expanduser().resolve()
    try:
        result = subprocess.run(
            ["git", "--git-dir", str(target), "rev-parse", "--is-bare-repository"],
            cwd=target,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def require_worktree_root(path: str | Path) -> None:
    """Fail closed with repair guidance before a checkout mutation."""
    if is_worktree_root(path):
        return
    enclosing = _toplevel(path, bounded=False)
    raise RuntimeError(
        f"Refusing Git mutation: {path} is not its own Git worktree; "
        f"discovered toplevel: {enclosing or '<none>'}. "
        "Move the existing contents aside and clone the intended repository "
        "at this path, or repair its .git metadata manually."
    )
