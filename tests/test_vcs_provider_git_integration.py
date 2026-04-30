"""Integration tests for the Git VCS provider using real git commands.

These tests exercise BareGitPlugin (via VCSPluginManager) against actual
temporary git repositories rather than mocking subprocess. They are skipped
when git is not available.
"""

import os
import shutil
import subprocess
import tempfile

import pluggy
import pytest
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.vcs_provider.plugins.bare_git import BareGitPlugin

_GIT_AVAILABLE = shutil.which("git") is not None

pytestmark = pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")


def _make_git_provider() -> VCSPluginManager:
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(BareGitPlugin())
    return VCSPluginManager(pm)


@pytest.fixture()
def git_repo(tmp_path: object) -> str:
    """Create a temporary git repo with one initial commit."""
    repo = str(tmp_path)
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    # Create initial commit
    readme = os.path.join(repo, "README.md")
    with open(readme, "w") as f:
        f.write("# Test Repo\n")
    subprocess.run(
        ["git", "add", "README.md"], cwd=repo, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    return repo


# === Tests for diff ===


# === Tests for get_branch_name ===


# === Tests for get_description ===


def test_integration_get_description(git_repo: str) -> None:
    """get_description returns the commit message for HEAD."""
    provider = _make_git_provider()
    success, desc = provider.get_description("HEAD", git_repo)

    assert success is True
    assert desc is not None
    assert "Initial commit" in desc


# === Tests for has_local_changes ===


# === Tests for commit ===


def test_integration_commit_on_current_branch(git_repo: str) -> None:
    """commit commits on the current branch without creating a new one."""
    # Stage a file
    new_file = os.path.join(git_repo, "feature.txt")
    with open(new_file, "w") as f:
        f.write("feature content\n")
    subprocess.run(
        ["git", "add", "feature.txt"], cwd=git_repo, capture_output=True, check=True
    )

    # Write a log message file
    logfile = os.path.join(git_repo, "commit_msg.txt")
    with open(logfile, "w") as f:
        f.write("Add feature\n")

    provider = _make_git_provider()
    success, error = provider.commit("my-feature", logfile, git_repo)

    assert success is True
    assert error is None

    # Verify we stayed on the original branch (master/main), not "my-feature"
    branch_success, branch_name = provider.get_branch_name(git_repo)
    assert branch_success is True
    assert branch_name != "my-feature"


# === Tests for amend ===


# === Tests for clean_workspace ===


# === Tests for rename_branch ===


# === Tests for apply_patch roundtrip ===


def test_integration_apply_patch_roundtrip(git_repo: str) -> None:
    """apply_patch applies a diff file generated from the same repo."""
    # Create a change and generate a raw diff (not via provider.diff which strips)
    readme = os.path.join(git_repo, "README.md")
    with open(readme, "a") as f:
        f.write("patch content\n")

    result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=git_repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    diff_text = result.stdout  # raw output, not stripped

    # Save the diff to a file OUTSIDE the repo (clean_workspace removes untracked)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as f:
        f.write(diff_text)
        patch_file = f.name

    provider = _make_git_provider()
    try:
        # Revert the change
        clean_ok, _ = provider.clean_workspace(git_repo)
        assert clean_ok is True

        # Apply the patch
        apply_ok, error = provider.apply_patch(patch_file, git_repo)
        assert apply_ok is True
        assert error is None

        # Verify the change was applied
        with open(readme) as f:
            content = f.read()
        assert "patch content" in content
    finally:
        os.unlink(patch_file)


# === Tests for stash_and_clean ===


def test_integration_stash_and_clean(git_repo: str) -> None:
    """stash_and_clean uses git stash and leaves workspace clean."""
    # Create a change
    with open(os.path.join(git_repo, "README.md"), "a") as f:
        f.write("stashed content\n")

    provider = _make_git_provider()
    success, error = provider.stash_and_clean("test-backup", git_repo)

    assert success is True
    assert error is None

    # Workspace should be clean
    has_changes_ok, changes = provider.has_local_changes(git_repo)
    assert has_changes_ok is True
    assert changes is None

    # Stash should contain our changes
    result = subprocess.run(
        ["git", "stash", "list"],
        cwd=git_repo,
        capture_output=True,
        text=True,
    )
    assert "test-backup" in result.stdout


# === Tests for archive and prune ===


def test_integration_prune(git_repo: str) -> None:
    """prune deletes a branch."""
    # Create a branch to prune
    subprocess.run(
        ["git", "checkout", "-b", "to-prune"],
        cwd=git_repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "checkout", "-"],
        cwd=git_repo,
        capture_output=True,
        check=True,
    )

    provider = _make_git_provider()
    success, error = provider.prune("to-prune", git_repo)

    assert success is True
    assert error is None

    # Branch should be gone
    branch_list = subprocess.run(
        ["git", "branch"],
        cwd=git_repo,
        capture_output=True,
        text=True,
    )
    assert "to-prune" not in branch_list.stdout
