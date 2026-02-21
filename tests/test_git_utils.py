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


def test_only_tracked_changes(git_repo):
    """Modified tracked file shows in diff."""
    readme = git_repo / "README"
    readme.write_text("changed\n")
    result = git_diff_with_untracked(str(git_repo))
    assert result is not None
    assert "README" in result
    assert "+changed" in result


def test_only_untracked_files(git_repo):
    """New untracked file shows in diff."""
    new_file = git_repo / "new_file.txt"
    new_file.write_text("hello\n")
    result = git_diff_with_untracked(str(git_repo))
    assert result is not None
    assert "new_file.txt" in result
    assert "+hello" in result


def test_tracked_and_untracked_combined(git_repo):
    """Both tracked changes and untracked files appear."""
    readme = git_repo / "README"
    readme.write_text("modified\n")
    new_file = git_repo / "added.py"
    new_file.write_text("print('hi')\n")
    result = git_diff_with_untracked(str(git_repo))
    assert result is not None
    assert "README" in result
    assert "added.py" in result


def test_filename_with_spaces(git_repo):
    """Untracked file with spaces in name is handled."""
    spaced = git_repo / "my file.txt"
    spaced.write_text("content\n")
    result = git_diff_with_untracked(str(git_repo))
    assert result is not None
    assert "my file.txt" in result
