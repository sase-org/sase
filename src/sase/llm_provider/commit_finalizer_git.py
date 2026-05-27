"""Git and artifact path helpers for commit finalization."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git_changed_files(repo_dir: str) -> list[str]:
    repo_dir = _normalize_path(repo_dir)
    if not Path(repo_dir).is_dir():
        return []
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_dir,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return _changed_files_from_git_status(result.stdout)


def _changed_files_from_git_status(status_text: str) -> list[str]:
    changed: list[str] = []
    for raw_line in status_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        changed.append(line[3:] if len(line) > 3 else line)
    return changed


def _normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))
