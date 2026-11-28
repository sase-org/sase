"""Tests for core utility modules (formerly sase_utils)."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.core.changespec import (
    changespec_name_to_branch,
    ensure_project_prefix,
    get_next_suffix_number,
    get_workspace_directory_for_patch,
)
from sase.core.paths import shorten_path
from sase.core.shell import run_workspace_command, strip_hook_prefix
from tests.git_lock_test_helpers import (
    absent_owner_facts,
    active_owner_facts,
    age_git_index_lock,
    incomplete_owner_facts,
    patch_git_lock_owner_probe,
)


def test_shorten_path_partial_home_match() -> None:
    """A home-looking substring outside the path prefix is not shortened."""
    home = str(Path.home())
    # Path that contains home directory but not at start
    path = f"/prefix{home}/file.txt"
    result = shorten_path(path)
    assert result == path


def test_get_workspace_directory_for_patch_extracts_basename() -> None:
    """Test that get_workspace_directory_for_patch extracts project basename."""
    mock_patch = MagicMock()
    mock_patch.file_path = "/some/path/my_project.sase"
    mock_patch.project_basename = "my_project"

    with patch("sase.running_field.get_workspace_directory") as mock_get_ws:
        mock_get_ws.return_value = "/workspace/my_project"
        get_workspace_directory_for_patch(mock_patch)
        # Should extract "my_project" from "my_project.sase"
        mock_get_ws.assert_called_once_with("my_project")


# Tests for strip_hook_prefix
def test_strip_hook_prefix_dollar() -> None:
    """Test strip_hook_prefix removes $ prefix."""
    assert strip_hook_prefix("$sase_hg_test") == "sase_hg_test"


# Tests for has_suffix


# Tests for get_next_suffix_number


def test_get_next_suffix_number_ignores_other_bases() -> None:
    """Test get_next_suffix_number ignores names with different bases."""
    existing = {"other__1", "other__2", "feature__1"}
    result = get_next_suffix_number("feature", existing)
    assert result == 2  # feature__1 (legacy) is taken, so next is 2


def test_get_next_suffix_number_checks_both_formats() -> None:
    """Test get_next_suffix_number skips slots taken by either suffix format."""
    existing = {"feature_1", "feature__2"}
    result = get_next_suffix_number("feature", existing)
    assert result == 3  # _1 (new) and __2 (legacy) are both taken


# Tests for run_workspace_command


def test_run_workspace_command_failure() -> None:
    """Test run_workspace_command returns failure on non-zero exit code."""
    with patch("sase.core.shell.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="some error", stdout="")
        success, error = run_workspace_command(["sase_hg_prune", "foo"], "/tmp")

    assert success is False
    assert error is not None
    assert "sase_hg_prune failed" in error
    assert "some error" in error


def test_run_workspace_command_command_not_found() -> None:
    """Test run_workspace_command handles FileNotFoundError."""
    with patch("sase.core.shell.subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError()
        success, error = run_workspace_command(["nonexistent_cmd"], "/tmp")

    assert success is False
    assert error == "nonexistent_cmd command not found"


def test_run_workspace_command_no_capture() -> None:
    """Test run_workspace_command with capture_output=False."""
    with patch("sase.core.shell.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        success, error = run_workspace_command(
            ["sase", "commit"], "/tmp", capture_output=False
        )

    assert success is True
    assert error is None
    mock_run.assert_called_once_with(
        ["sase", "commit"], cwd="/tmp", capture_output=False, text=True, check=False
    )


def test_run_workspace_git_command_recovers_stale_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "feature.txt").write_text("feature\n", encoding="utf-8")
    lock = tmp_path / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    age_git_index_lock(lock)
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001,0.001")
    observations = patch_git_lock_owner_probe(
        monkeypatch,
        "sase.core.shell",
        tmp_path,
        absent_owner_facts,
    )

    success, error = run_workspace_command(
        ["git", "add", "feature.txt"],
        str(tmp_path),
    )

    assert success is True, f"{error}\n{observations}"
    assert error is None
    assert not lock.exists()
    assert observations
    assert observations[-1]["facts"]["probe_status"] == "complete"


@pytest.mark.parametrize("owner_kind", ["absent", "active", "incomplete"])
def test_workspace_git_lock_owner_facts_control_stale_lock_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    owner_kind: str,
) -> None:
    from sase.git_lock_retry import git_index_lock_path

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "feature.txt").write_text("feature\n", encoding="utf-8")
    lock = tmp_path / ".git" / "index.lock"
    lock.write_bytes(b"fixture-lock-content")
    age_git_index_lock(lock)
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001,0.001")

    # Initialize the cached policy before injecting the per-call probe. This
    # ensures the caller seam does not depend on patching policy initialization.
    assert git_index_lock_path(tmp_path) == lock
    permission_denied_reason = "permission denied reading /proc/4242/fd"
    probes = {
        "absent": absent_owner_facts,
        "active": active_owner_facts,
        "incomplete": lambda **kwargs: incomplete_owner_facts(
            **kwargs, reason=permission_denied_reason
        ),
    }
    observations = patch_git_lock_owner_probe(
        monkeypatch,
        "sase.core.shell",
        tmp_path,
        probes[owner_kind],
    )

    success, error = run_workspace_command(["git", "add", "feature.txt"], str(tmp_path))

    assert observations
    assert observations[-1]["lock_path"] == lock
    assert success is (owner_kind == "absent"), f"{error}\n{caplog.text}"
    if owner_kind == "absent":
        assert error is None
        assert not lock.exists()
        assert (
            "feature.txt"
            in subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=tmp_path,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
    else:
        assert error is not None and "index.lock" in error
        assert lock.read_bytes() == b"fixture-lock-content"
        assert "Preserving git index lock" in caplog.text
        assert (
            subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=tmp_path,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            == ""
        )
        if owner_kind == "incomplete":
            assert observations[-1]["facts"]["probe_reason"] == permission_denied_reason


# Tests for changespec_name_to_branch


def test_ensure_project_prefix_missing() -> None:
    """Prefix is prepended when missing."""
    assert ensure_project_prefix("sase", "fix_split") == "sase_fix_split"


def test_ensure_project_prefix_already_present() -> None:
    """No-op when prefix is already present."""
    assert ensure_project_prefix("sase", "sase_fix_split") == "sase_fix_split"


def test_ensure_project_prefix_partial_match() -> None:
    """A name that starts with the project string but not the full prefix."""
    assert ensure_project_prefix("sase", "sasefoo") == "sase_sasefoo"


# Tests for changespec_name_to_branch


def test_changespec_name_to_branch_no_prefix() -> None:
    """Name without project prefix falls through to hyphen conversion."""
    assert changespec_name_to_branch("dull_basin__1", "sase") == "dull-basin"
