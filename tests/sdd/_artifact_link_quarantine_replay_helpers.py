"""Shared helpers for quarantine replay evidence tests.

Public names in this already-private module are shared by the split
``test_artifact_link_quarantine_replay_*`` modules so those modules never
import a ``_``-prefixed name from each other.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.core.rust import require_rust_binding
from tests.sdd._artifact_link_event_store_test_helpers import edge_event


def event_digest(event: dict[str, object]) -> str:
    return str(require_rust_binding("artifact_link_event_digest")(event))


def run_git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout


def init_repo(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "GIT_AUTHOR_EMAIL": "sase@example.test",
        "GIT_AUTHOR_NAME": "SASE Tests",
        "GIT_COMMITTER_EMAIL": "sase@example.test",
        "GIT_COMMITTER_NAME": "SASE Tests",
    }.items():
        monkeypatch.setenv(key, value)
    run_git(root, "init", "-q")
    run_git(root, "config", "user.name", "SASE Tests")
    run_git(root, "config", "user.email", "sase@example.test")
    run_git(root, "config", "commit.gpgsign", "false")


def commit_all(root: Path, message: str, when: str | None = None) -> None:
    env = None
    if when is not None:
        import os

        env = dict(os.environ)
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    run_git(root, "add", "-A", env=env)
    run_git(root, "commit", "-qm", message, env=env)


def colliding_pair(
    *, origin: str = "manual"
) -> tuple[dict[str, object], dict[str, object]]:
    created_at = "2026-09-09T12:00:00Z"
    first = edge_event(
        "a" * 32,
        target="plan:202608/original.md",
        description="original payload",
        origin=origin,
        created_at=created_at,
    )
    second = edge_event(
        "a" * 32,
        target="plan:202608/replay.md",
        description="replay payload",
        origin=origin,
        created_at=created_at,
    )
    return first, second
