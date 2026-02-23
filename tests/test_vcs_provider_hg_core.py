"""Tests for the Mercurial VCS provider — core operations.

Covers: diff_revision, apply_patch, apply_patches, add_remove, clean_workspace.
"""

from unittest.mock import MagicMock, patch

from sase.vcs_provider.plugins.hg import HgPlugin

# === Tests for diff_revision ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_diff_revision_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_diff_revision on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="diff output", stderr="")

    plugin = HgPlugin()
    success, diff_text = plugin.vcs_diff_revision("abc123", "/workspace")

    assert success is True
    assert diff_text == "diff output"
    assert mock_run.call_args[0][0] == ["hg", "diff", "-c", "abc123"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_diff_revision_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_diff_revision on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="unknown revision"
    )

    plugin = HgPlugin()
    success, error = plugin.vcs_diff_revision("bad_rev", "/workspace")

    assert success is False
    assert error is not None
    assert "hg diff failed" in error


# === Tests for apply_patch ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
@patch("os.path.exists", return_value=True)
def test_hg_apply_patch_success(mock_exists: MagicMock, mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_apply_patch on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = HgPlugin()
    success, error = plugin.vcs_apply_patch("/tmp/fix.patch", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["hg", "import", "--no-commit", "/tmp/fix.patch"]


@patch("os.path.exists", return_value=False)
def test_hg_apply_patch_file_not_found(mock_exists: MagicMock) -> None:
    """Test HgPlugin.vcs_apply_patch when file doesn't exist."""
    plugin = HgPlugin()
    success, error = plugin.vcs_apply_patch("/tmp/missing.patch", "/workspace")

    assert success is False
    assert error is not None
    assert "Diff file not found" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
@patch("os.path.exists", return_value=True)
def test_hg_apply_patch_failure(mock_exists: MagicMock, mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_apply_patch when hg import fails."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="patch does not apply"
    )

    plugin = HgPlugin()
    success, error = plugin.vcs_apply_patch("/tmp/bad.patch", "/workspace")

    assert success is False
    assert error is not None
    assert "patch does not apply" in error


# === Tests for apply_patches ===


def test_hg_apply_patches_empty_list() -> None:
    """Test HgPlugin.vcs_apply_patches with empty list."""
    plugin = HgPlugin()
    success, error = plugin.vcs_apply_patches([], "/workspace")

    assert success is True
    assert error is None


@patch("sase.vcs_provider._command_runner.subprocess.run")
@patch("os.path.exists", return_value=True)
def test_hg_apply_patches_success(mock_exists: MagicMock, mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_apply_patches on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = HgPlugin()
    success, error = plugin.vcs_apply_patches(
        ["/tmp/a.patch", "/tmp/b.patch"], "/workspace"
    )

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == [
        "hg",
        "import",
        "--no-commit",
        "/tmp/a.patch",
        "/tmp/b.patch",
    ]


@patch("os.path.exists", side_effect=[True, False])
def test_hg_apply_patches_missing_file(mock_exists: MagicMock) -> None:
    """Test HgPlugin.vcs_apply_patches when a file is missing."""
    plugin = HgPlugin()
    success, error = plugin.vcs_apply_patches(
        ["/tmp/a.patch", "/tmp/missing.patch"], "/workspace"
    )

    assert success is False
    assert error is not None
    assert "Diff file not found" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
@patch("os.path.exists", return_value=True)
def test_hg_apply_patches_failure(mock_exists: MagicMock, mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_apply_patches when hg import fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="conflict")

    plugin = HgPlugin()
    success, error = plugin.vcs_apply_patches(["/tmp/a.patch"], "/workspace")

    assert success is False
    assert error is not None
    assert "conflict" in error


# === Tests for add_remove ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_add_remove_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_add_remove on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = HgPlugin()
    success, error = plugin.vcs_add_remove("/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["hg", "addremove"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_add_remove_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_add_remove on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not a hg repo")

    plugin = HgPlugin()
    success, error = plugin.vcs_add_remove("/workspace")

    assert success is False
    assert error is not None
    assert "hg addremove failed" in error


# === Tests for clean_workspace ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_clean_workspace_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_clean_workspace on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = HgPlugin()
    success, error = plugin.vcs_clean_workspace("/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_count == 2
    assert mock_run.call_args_list[0][0][0] == ["hg", "update", "--clean", "."]
    assert mock_run.call_args_list[1][0][0] == ["hg", "clean"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_clean_workspace_revert_fails(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_clean_workspace when revert step fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="revert error")

    plugin = HgPlugin()
    success, error = plugin.vcs_clean_workspace("/workspace")

    assert success is False
    assert error is not None
    assert "hg update --clean failed" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_clean_workspace_clean_fails(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_clean_workspace when clean step fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # update --clean succeeds
        MagicMock(returncode=1, stdout="", stderr="clean error"),  # hg clean fails
    ]

    plugin = HgPlugin()
    success, error = plugin.vcs_clean_workspace("/workspace")

    assert success is False
    assert error is not None
    assert "hg clean failed" in error
