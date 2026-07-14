"""Helpers for the per-clone ``.git/info/exclude`` ignore file.

This file behaves like ``.gitignore`` but is local to a clone and not
checked in. SASE uses it to keep workspace-scoped scratch state (``.sase/``)
and host-scoped linked clones (``/sase/repos/``) untracked, so ``git clean
-fd`` invoked by embedded ``#git`` pre-steps does not wipe SASE-managed
files before the project's tracked ``.gitignore`` is initialized.
"""

from __future__ import annotations

from pathlib import Path

SASE_GIT_INFO_EXCLUDE_PATTERNS = (".sase/", "/sase/repos/")


def _resolve_git_dir(workspace_dir: str) -> Path | None:
    """Resolve ``.git`` for *workspace_dir*, following worktree pointers.

    Returns ``None`` when the directory does not look like a git checkout.
    """
    git_path = Path(workspace_dir) / ".git"
    if git_path.is_dir():
        return git_path
    if git_path.is_file():
        try:
            content = git_path.read_text(encoding="utf-8")
        except OSError:
            return None
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("gitdir:"):
                rel = line.split(":", 1)[1].strip()
                if not rel:
                    return None
                resolved = (Path(workspace_dir) / rel).resolve()
                if resolved.is_dir():
                    return resolved
                return None
        return None
    return None


def ensure_git_info_exclude_entry(workspace_dir: str, pattern: str) -> None:
    """Idempotently append *pattern* to ``<workspace>/.git/info/exclude``.

    - No-op when *workspace_dir* is not a git checkout.
    - No-op when *pattern* is already present (non-comment, exact match).
    - Tolerates worktrees (``.git`` as a file with ``gitdir:`` pointer).
    - Swallows ``OSError`` so a degraded path never blocks the caller.
    """
    try:
        git_dir = _resolve_git_dir(workspace_dir)
        if git_dir is None:
            return
        info_dir = git_dir / "info"
        exclude_path = info_dir / "exclude"

        existing = ""
        if exclude_path.exists():
            try:
                existing = exclude_path.read_text(encoding="utf-8")
            except OSError:
                return
            for raw in existing.splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line == pattern:
                    return

        info_dir.mkdir(parents=True, exist_ok=True)
        sep = "" if not existing or existing.endswith("\n") else "\n"
        with open(exclude_path, "a", encoding="utf-8") as f:
            f.write(f"{sep}{pattern}\n")
    except OSError:
        return


def ensure_sase_git_info_excludes(workspace_dir: str) -> None:
    """Install every SASE-managed per-clone ignore pattern."""

    for pattern in SASE_GIT_INFO_EXCLUDE_PATTERNS:
        ensure_git_info_exclude_entry(workspace_dir, pattern)


__all__ = [
    "SASE_GIT_INFO_EXCLUDE_PATTERNS",
    "ensure_git_info_exclude_entry",
    "ensure_sase_git_info_excludes",
]
