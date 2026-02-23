"""Tests for the Mercurial VCS provider — query/info methods.

Covers: get_description, has_local_changes, get_workspace_name, reword,
reword_add_tag, get_change_url, get_bug_number, mail, fix, upload,
find_reviewers, rewind.
"""

from unittest.mock import MagicMock, patch

from sase.vcs_provider.plugins.hg import HgPlugin

# === Tests for get_description ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_get_description_full(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_get_description returns full description."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="Full commit message\n\nBody text\n", stderr=""
    )

    plugin = HgPlugin()
    success, desc = plugin.vcs_get_description("abc123", "/workspace", short=False)

    assert success is True
    assert desc is not None
    assert "Full commit message" in desc
    assert mock_run.call_args[0][0] == ["cl_desc", "-r", "abc123"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_get_description_short(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_get_description with short=True."""
    mock_run.return_value = MagicMock(returncode=0, stdout="Short subject\n", stderr="")

    plugin = HgPlugin()
    success, desc = plugin.vcs_get_description("abc123", "/workspace", short=True)

    assert success is True
    assert desc is not None
    assert "Short subject" in desc
    assert mock_run.call_args[0][0] == ["cl_desc", "-s"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_get_description_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_get_description on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="unknown revision"
    )

    plugin = HgPlugin()
    success, error = plugin.vcs_get_description("bad_rev", "/workspace", short=False)

    assert success is False
    assert error is not None
    assert "unknown revision" in error


# === Tests for has_local_changes ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_has_local_changes_with_changes(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_has_local_changes when changes exist."""
    mock_run.return_value = MagicMock(returncode=0, stdout="M file.py\n", stderr="")

    plugin = HgPlugin()
    success, text = plugin.vcs_has_local_changes("/workspace")

    assert success is True
    assert text is not None
    assert "file.py" in text


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_has_local_changes_clean(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_has_local_changes when workspace is clean."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = HgPlugin()
    success, text = plugin.vcs_has_local_changes("/workspace")

    assert success is True
    assert text is None


# === Tests for get_workspace_name ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_get_workspace_name_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_get_workspace_name on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="my-workspace\n", stderr="")

    plugin = HgPlugin()
    success, name = plugin.vcs_get_workspace_name("/workspace")

    assert success is True
    assert name == "my-workspace"


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_get_workspace_name_empty(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_get_workspace_name returns None when empty."""
    mock_run.return_value = MagicMock(returncode=0, stdout="\n", stderr="")

    plugin = HgPlugin()
    success, name = plugin.vcs_get_workspace_name("/workspace")

    assert success is True
    assert name is None


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_get_workspace_name_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_get_workspace_name on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")

    plugin = HgPlugin()
    success, error = plugin.vcs_get_workspace_name("/workspace")

    assert success is False
    assert error is not None
    assert "workspace_name command failed" in error


# === Tests for reword ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_reword_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_reword on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = HgPlugin()
    success, error = plugin.vcs_reword("new description", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["sase_hg_reword", "new description"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_reword_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_reword on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="reword error")

    plugin = HgPlugin()
    success, error = plugin.vcs_reword("desc", "/workspace")

    assert success is False
    assert error is not None
    assert "sase_hg_reword failed" in error


# === Tests for reword_add_tag ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_reword_add_tag_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_reword_add_tag on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = HgPlugin()
    success, error = plugin.vcs_reword_add_tag("BUG", "12345", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == [
        "sase_hg_reword",
        "--add-tag",
        "BUG",
        "12345",
    ]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_reword_add_tag_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_reword_add_tag on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="reword error")

    plugin = HgPlugin()
    success, error = plugin.vcs_reword_add_tag("BUG", "12345", "/workspace")

    assert success is False
    assert error is not None
    assert "sase_hg_reword failed" in error


# === Tests for get_change_url ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_get_change_url_with_cl(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_get_change_url when CL number exists."""
    mock_run.return_value = MagicMock(returncode=0, stdout="12345\n", stderr="")

    plugin = HgPlugin()
    success, url = plugin.vcs_get_change_url("/workspace")

    assert success is True
    assert url == "http://cl/12345"


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_get_change_url_no_cl(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_get_change_url when no CL number."""
    mock_run.return_value = MagicMock(returncode=0, stdout="not_a_number\n", stderr="")

    plugin = HgPlugin()
    success, url = plugin.vcs_get_change_url("/workspace")

    assert success is True
    assert url is None


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_get_change_url_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_get_change_url when branch_number command fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")

    plugin = HgPlugin()
    success, url = plugin.vcs_get_change_url("/workspace")

    assert success is False
    assert url is None


# === Tests for get_bug_number ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_get_bug_number_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_get_bug_number on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="b/54321\n", stderr="")

    plugin = HgPlugin()
    success, bug = plugin.vcs_get_bug_number("/workspace")

    assert success is True
    assert bug == "b/54321"


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_get_bug_number_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_get_bug_number on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")

    plugin = HgPlugin()
    success, error = plugin.vcs_get_bug_number("/workspace")

    assert success is False
    assert error is not None
    assert "sase_hg_branch_bug command failed" in error


# === Tests for mail ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_mail_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_mail on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = HgPlugin()
    success, error = plugin.vcs_mail("abc123", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["hg", "mail", "-r", "abc123"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_mail_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_mail on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="mail error")

    plugin = HgPlugin()
    success, error = plugin.vcs_mail("abc123", "/workspace")

    assert success is False
    assert error is not None
    assert "hg mail failed" in error


# === Tests for fix ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_fix_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_fix on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = HgPlugin()
    success, error = plugin.vcs_fix("/workspace")

    assert success is True
    assert error is None
    # fix uses _run_shell
    assert mock_run.call_args[0][0] == "hg fix"


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_fix_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_fix on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="fix error")

    plugin = HgPlugin()
    success, error = plugin.vcs_fix("/workspace")

    assert success is False
    assert error is not None
    assert "hg fix failed" in error


# === Tests for upload ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_upload_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_upload on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = HgPlugin()
    success, error = plugin.vcs_upload("/workspace")

    assert success is True
    assert error is None
    # upload uses _run_shell
    assert mock_run.call_args[0][0] == "hg upload tree"


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_upload_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_upload on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="upload error")

    plugin = HgPlugin()
    success, error = plugin.vcs_upload("/workspace")

    assert success is False
    assert error is not None
    assert "hg upload tree failed" in error


# === Tests for find_reviewers ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_find_reviewers_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_find_reviewers on success."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="reviewer1,reviewer2\n", stderr=""
    )

    plugin = HgPlugin()
    success, reviewers = plugin.vcs_find_reviewers("12345", "/workspace")

    assert success is True
    assert reviewers is not None
    assert "reviewer1" in reviewers
    assert mock_run.call_args[0][0] == ["p4", "findreviewers", "-c", "12345"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_find_reviewers_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_find_reviewers on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="p4 error")

    plugin = HgPlugin()
    success, error = plugin.vcs_find_reviewers("12345", "/workspace")

    assert success is False
    assert error is not None
    assert "p4 error" in error


# === Tests for rewind ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_rewind_success(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_rewind on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = HgPlugin()
    success, error = plugin.vcs_rewind(["/tmp/a.diff", "/tmp/b.diff"], "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == [
        "sase_hg_rewind",
        "/tmp/a.diff",
        "/tmp/b.diff",
    ]
    # Verify 600s timeout
    assert mock_run.call_args[1]["timeout"] == 600


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_rewind_failure(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_rewind on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="rewind error")

    plugin = HgPlugin()
    success, error = plugin.vcs_rewind(["/tmp/a.diff"], "/workspace")

    assert success is False
    assert error is not None
    assert "sase_hg_rewind failed" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_hg_rewind_timeout(mock_run: MagicMock) -> None:
    """Test HgPlugin.vcs_rewind handles timeout."""
    import subprocess

    mock_run.side_effect = subprocess.TimeoutExpired(cmd="sase_hg_rewind", timeout=600)

    plugin = HgPlugin()
    success, error = plugin.vcs_rewind(["/tmp/a.diff"], "/workspace")

    assert success is False
    assert error is not None
    assert "timed out" in error
