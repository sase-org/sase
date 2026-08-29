"""Tests for adopting a calling runner's numbered workspace claim."""

from __future__ import annotations

import os
from pathlib import Path

from sase.running_field import (
    WorkspaceClaim,
    find_runner_numbered_workspace,
    runner_has_placeholder_workspace,
)
from tests._running_field_helpers import create_project_file_with_running


def test_finds_parent_numbered_pool_claim(tmp_path: Path) -> None:
    parent_pid = os.getppid()
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(12, "ace(run)-launcher", "feature", pid=parent_pid)
        ],
    )

    assert find_runner_numbered_workspace(project_file) == 12


def test_explicit_pid_overrides_parent(tmp_path: Path) -> None:
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(12, "ace(run)-launcher", "feature", pid=os.getppid()),
            WorkspaceClaim(15, "ace(run)-other", "other", pid=4242),
        ],
    )

    assert find_runner_numbered_workspace(project_file, pid=4242) == 15
    assert find_runner_numbered_workspace(project_file, pid=os.getppid()) == 12


def test_ignores_primary_placeholder_claim(tmp_path: Path) -> None:
    parent_pid = os.getppid()
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(0, "ace(run)-launcher", "feature", pid=parent_pid)
        ],
    )

    assert find_runner_numbered_workspace(project_file) is None


def test_detects_parent_placeholder_claim(tmp_path: Path) -> None:
    parent_pid = os.getppid()
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(0, "ace(run)-launcher", "feature", pid=parent_pid)
        ],
    )

    assert runner_has_placeholder_workspace(project_file)
    assert not runner_has_placeholder_workspace(project_file, pid=4242)


def test_ignores_reserved_workspace_numbers(tmp_path: Path) -> None:
    parent_pid = os.getppid()
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(5, "ace(run)-launcher", "feature", pid=parent_pid)
        ],
    )

    assert find_runner_numbered_workspace(project_file) is None


def test_ignores_numbered_claim_owned_by_another_pid(tmp_path: Path) -> None:
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(12, "ace(run)-other", "other", pid=11111),
        ],
    )

    assert find_runner_numbered_workspace(project_file) is None


def test_picks_lowest_numbered_claim_when_parent_holds_two(tmp_path: Path) -> None:
    parent_pid = os.getppid()
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(23, "gh-gh_acme__widget", "feature", pid=parent_pid),
            WorkspaceClaim(12, "ace(run)-launcher", "feature", pid=parent_pid),
        ],
    )

    assert find_runner_numbered_workspace(project_file) == 12


def test_missing_project_file_is_not_adopted(tmp_path: Path) -> None:
    assert find_runner_numbered_workspace(str(tmp_path / "missing.sase")) is None
