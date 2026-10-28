"""Shared builders for reset-and-replay tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from sase.workspace_provider.ownership import (
    AccessKind,
    MutationOrigin,
    OperationContext,
)
from tests.workspace_provider.test_rescue._helpers import redirect_state

__all__ = [
    "advance_origin",
    "clone_repo",
    "init_origin",
    "operation_context",
    "redirect_rescue_state",
    "repo_head",
    "run_git",
    "run_git_capture",
]


@pytest.fixture(autouse=True)
def redirect_rescue_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point rescue-store state at *tmp_path* for every reset-replay test."""
    redirect_state(tmp_path, monkeypatch)


def run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def run_git_capture(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def init_origin(path: Path) -> None:
    path.mkdir(parents=True)
    run_git(["init", "-q", "-b", "main"], path)
    run_git(["config", "user.email", "test@test.com"], path)
    run_git(["config", "user.name", "Test"], path)
    (path / "README.md").write_text("origin v1\n", encoding="utf-8")
    run_git(["add", "."], path)
    run_git(["commit", "-q", "-m", "init"], path)


def clone_repo(origin: Path, target: Path) -> Path:
    run_git(["clone", "-q", str(origin), str(target)], target.parent)
    run_git(["config", "user.email", "test@test.com"], target)
    run_git(["config", "user.name", "Test"], target)
    return target


def repo_head(repo: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def advance_origin(origin: Path, content: str) -> None:
    (origin / "README.md").write_text(content, encoding="utf-8")
    run_git(["commit", "-aq", "-m", "advance"], origin)


def operation_context(
    checkout: Path,
    primary: Path,
    *,
    access_kind: AccessKind = AccessKind.LEASED_OPERATIONAL,
    workspace_num: int = 10,
    no_claim: bool = False,
) -> OperationContext:
    return OperationContext(
        project="demo",
        access_kind=access_kind,
        mutation_origin=MutationOrigin.MACHINE,
        workspace_num=workspace_num,
        checkout_dir=checkout,
        primary_checkout_dir=primary,
        project_file=None,
        claim_pid=None if no_claim else os.getpid(),
        claim_workflow="chop:demo",
    )
