"""Shared git and filesystem helpers for stale-replay recovery."""

from __future__ import annotations

from pathlib import Path

from sase.agents_sync.git import GitRunner
from sase.agents_sync.git_sync_ops import agents_git_error
from sase.agents_sync.io import AgentsSyncFormatError


def git_text(repo: Path, git_runner: GitRunner, args: list[str], op: str) -> str:
    result = git_runner(repo, args, op=f"agents_sync.{op}")
    if result.returncode != 0:
        raise AgentsSyncFormatError(
            agents_git_error(f"git {' '.join(args)} failed", result)
        )
    return result.stdout.strip()


def file_bytes(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    return path.read_bytes()
