"""Tests for sase.git_utils.git_diff_with_untracked()."""

import subprocess

import pytest

from sase.git_utils import git_diff_with_untracked


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    # Need at least one commit for HEAD to exist
    initial = tmp_path / "README"
    initial.write_text("init\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path


def test_no_changes(git_repo):
    """No tracked or untracked changes → None."""
    assert git_diff_with_untracked(str(git_repo)) is None
