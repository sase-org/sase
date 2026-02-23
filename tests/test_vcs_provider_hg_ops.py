"""Tests for the Mercurial VCS provider — commit and branch operations.

Covers: commit, rename_branch (failure), rebase, archive, prune.
"""

from unittest.mock import MagicMock, patch

from sase.vcs_provider.plugins.hg import HgPlugin

# === Tests for commit ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_commit_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_commit on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = HgPlugin()
    success, error = plugin.vcs_commit("feature", "/tmp/msg.txt", "/workspace")

    assert success is True
    assert error is None
    # commit uses _run_shell, so call_args[0][0] is a string
    cmd_str = mock_run.call_args[0][0]
    assert 'hg commit --name "feature" --logfile "/tmp/msg.txt"' == cmd_str


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_commit_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_commit on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="nothing to commit"
    )

    plugin = HgPlugin()
    success, error = plugin.vcs_commit("feature", "/tmp/msg.txt", "/workspace")

    assert success is False
    assert error is not None
    assert "hg commit failed" in error


# === Tests for rename_branch (failure case) ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_rename_branch_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_rename_branch on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="rename failed")

    plugin = HgPlugin()
    success, error = plugin.vcs_rename_branch("bad_name", "/workspace")

    assert success is False
    assert error is not None
    assert "sase_hg_rename failed" in error


# === Tests for rebase ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_rebase_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_rebase on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = HgPlugin()
    success, error = plugin.vcs_rebase("feature", "main", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["sase_hg_rebase", "feature", "main"]
    # Verify 600s timeout
    assert mock_run.call_args[1]["timeout"] == 600


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_rebase_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_rebase on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="merge conflict")

    plugin = HgPlugin()
    success, error = plugin.vcs_rebase("feature", "main", "/workspace")

    assert success is False
    assert error is not None
    assert "sase_hg_rebase failed" in error


# === Tests for archive ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_archive_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_archive on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = HgPlugin()
    success, error = plugin.vcs_archive("old-feature", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["sase_hg_archive", "old-feature"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_archive_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_archive on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="archive error")

    plugin = HgPlugin()
    success, error = plugin.vcs_archive("old-feature", "/workspace")

    assert success is False
    assert error is not None
    assert "sase_hg_archive failed" in error


# === Tests for prune ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_prune_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_prune on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = HgPlugin()
    success, error = plugin.vcs_prune("dead-branch", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["sase_hg_prune", "dead-branch"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_prune_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_prune on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="prune error")

    plugin = HgPlugin()
    success, error = plugin.vcs_prune("nonexistent", "/workspace")

    assert success is False
    assert error is not None
    assert "sase_hg_prune failed" in error
