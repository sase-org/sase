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


def _head_message(repo: str) -> str:
    out = subprocess.run(
        ["git", "log", "--format=%B", "-n1", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


def _amend_head_message(repo: str, message: str) -> None:
    subprocess.run(
        ["git", "commit", "--amend", "-m", message],
        cwd=repo,
        capture_output=True,
        check=True,
    )


def test_integration_amend_preserves_type_tag_with_untagged_message(
    git_repo: str,
) -> None:
    """A fresh, untagged amend message inherits HEAD's SASE_TYPE= tag."""
    _amend_head_message(
        git_repo, "feat: tracked work\n\nSASE_TYPE=stitch\nSASE_AGENT=someagent"
    )
    provider = _make_git_provider()

    success, error = provider.amend("chore: fresh untagged message", git_repo)

    assert success is True, error
    message = _head_message(git_repo)
    assert message.startswith("chore: fresh untagged message")
    assert "SASE_TYPE=stitch" in message
    assert "SASE_AGENT=someagent" in message


def test_integration_amend_rewind_message_classifies_as_stitch(git_repo: str) -> None:
    """The rewind workflow's literal ``[rewind] (N)`` message stays classified
    as ``stitch`` after amending, not just carrying the substring."""
    _amend_head_message(git_repo, "feat: tracked work\n\nSASE_TYPE=stitch")
    provider = _make_git_provider()

    success, error = provider.amend("[rewind] (3)", git_repo)

    assert success is True, error
    message = _head_message(git_repo)

    from sase.core.rust import require_rust_binding

    classify = require_rust_binding("classify_commit_origin")
    assert classify(message.strip("\n")) == "stitch"


def test_integration_amend_with_no_head_footer_leaves_message_untouched(
    git_repo: str,
) -> None:
    """Amending HEAD's untagged initial commit leaves the caller's message as-is."""
    provider = _make_git_provider()

    success, error = provider.amend("chore: plain amend", git_repo)

    assert success is True, error
    assert _head_message(git_repo).strip("\n") == "chore: plain amend"


def test_integration_amend_is_idempotent(git_repo: str) -> None:
    """Amending twice with the same note does not duplicate or reorder tags."""
    _amend_head_message(git_repo, "feat: tracked work\n\nSASE_TYPE=stitch")
    provider = _make_git_provider()

    ok1, err1 = provider.amend("[rewind] (3)", git_repo)
    assert ok1 is True, err1
    first_message = _head_message(git_repo)

    ok2, err2 = provider.amend("[rewind] (3)", git_repo)
    assert ok2 is True, err2
    second_message = _head_message(git_repo)

    assert first_message == second_message
    assert first_message.count("SASE_TYPE=") == 1


def test_integration_amend_caller_supplied_type_wins_over_inherited(
    git_repo: str,
) -> None:
    """A TYPE tag already present in the caller's message beats HEAD's."""
    _amend_head_message(git_repo, "feat: tracked work\n\nSASE_TYPE=stitch")
    provider = _make_git_provider()

    success, error = provider.amend(
        "chore: manual override\n\nSASE_TYPE=manual", git_repo
    )

    assert success is True, error
    message = _head_message(git_repo)
    assert message.count("SASE_TYPE=") == 1
    assert "SASE_TYPE=manual" in message
    assert "SASE_TYPE=stitch" not in message


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


def test_integration_archive_current_branch(git_repo: str) -> None:
    """archive succeeds even when the target branch is currently checked out."""
    provider = _make_git_provider()

    # The branch we start on is the repo's default branch.
    default_ok, default_branch = provider.get_branch_name(git_repo)
    assert default_ok is True
    assert default_branch is not None

    # Make _get_default_branch resolve to it, mirroring a cloned workspace
    # where origin/HEAD points at the default branch.
    subprocess.run(
        [
            "git",
            "symbolic-ref",
            "refs/remotes/origin/HEAD",
            f"refs/remotes/origin/{default_branch}",
        ],
        cwd=git_repo,
        capture_output=True,
        check=True,
    )

    # Create and check out a feature branch with its own commit.
    subprocess.run(
        ["git", "checkout", "-b", "feature-to-archive"],
        cwd=git_repo,
        capture_output=True,
        check=True,
    )
    feature = os.path.join(git_repo, "feature.txt")
    with open(feature, "w") as f:
        f.write("feature\n")
    subprocess.run(
        ["git", "add", "feature.txt"], cwd=git_repo, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "feature commit"],
        cwd=git_repo,
        capture_output=True,
        check=True,
    )

    # Archive while still ON feature-to-archive.
    success, error = provider.archive("feature-to-archive", git_repo)
    assert success is True, error
    assert error is None

    # The archive tag exists.
    tags = subprocess.run(["git", "tag"], cwd=git_repo, capture_output=True, text=True)
    assert "archive/feature-to-archive" in tags.stdout

    # The local branch is gone.
    branches = subprocess.run(
        ["git", "branch"], cwd=git_repo, capture_output=True, text=True
    )
    assert "feature-to-archive" not in branches.stdout

    # The worktree is left on the (still-existing) default branch.
    cur_ok, cur_branch = provider.get_branch_name(git_repo)
    assert cur_ok is True
    assert cur_branch == default_branch
    assert default_branch in branches.stdout


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
