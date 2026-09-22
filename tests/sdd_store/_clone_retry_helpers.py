"""Shared staging helpers for sidecar clone retry tests."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

import pytest

from tests.sdd_store._helpers import (
    clone,
    commit_all,
    git,
    init_bare_repo,
    init_git_identity,
)


def hold_remote_clone_slot(lock_dir: Path) -> int:
    lock_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_dir / "slot-0.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def stage_clone_path(args: list[str]) -> Path:
    return Path(args[-1])


def write_partial_clone(args: list[str]) -> Path:
    target = stage_clone_path(args)
    target.mkdir(parents=True, exist_ok=True)
    (target / "partial").write_text("incomplete", encoding="utf-8")
    return target


def write_valid_clone(args: list[str]) -> Path:
    target = stage_clone_path(args)
    remote = args[-2]
    target.mkdir(parents=True, exist_ok=True)
    git(["init", "-q", "-b", "main"], target)
    init_git_identity(target)
    (target / "README.md").write_text("# staged clone\n", encoding="utf-8")
    commit_all(target, "Initialize staged clone")
    git(["remote", "add", "origin", remote], target)
    git(["update-ref", "refs/remotes/origin/main", "HEAD"], target)
    git(["branch", "--set-upstream-to=origin/main", "main"], target)
    return target


def normalized_clone_calls(
    calls: list[list[str]],
    clone_dir: Path,
) -> list[list[str]]:
    normalized: list[list[str]] = []
    for args in calls:
        stage = stage_clone_path(args)
        assert stage != clone_dir
        assert stage.name == "clone"
        assert stage.parent.parent == clone_dir.parent / ".sase-sdd-clone-staging"
        normalized.append([*args[:-1], str(clone_dir)])
    return normalized


def seed_remote(tmp_path: Path, name: str = "remote.git") -> Path:
    remote = tmp_path / name
    seed = tmp_path / f"{name}-seed"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("# Plans\n", encoding="utf-8")
    commit_all(seed, "Initialize plans")
    git(["push", "-u", "origin", "main"], seed)
    return remote


def fake_clone_retryability(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_is_retryable(detail: str) -> bool:
        folded = detail.casefold()
        return "early eof" in folded or "unexpected disconnect" in folded

    monkeypatch.setattr(
        "sase.sdd._store_clone_remote.is_retryable_git_clone_failure",
        fake_is_retryable,
    )
