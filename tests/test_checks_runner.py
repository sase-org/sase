"""Tests for the checks_runner module."""

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch as patch_ctx

import pytest
from sase.ace.scheduler.checks_runner import (
    CHECK_COMPLETE_MARKER,
    CHECK_TYPE_CL_SUBMITTED,
    CHECK_TYPE_REVIEWER_COMMENTS,
    _extract_change_identifier,
    _get_pending_checks,
    _handle_cl_submitted_completion,
    _parse_check_completion,
    has_pending_check,
    process_pending_checks_for,
    reap_orphan_check_files,
    scan_all_pending_checks,
    start_reviewer_comments_check,
)
from sase.workspace_provider import SUBMITTED_CHECK_EXIT_CODE_CLOSED

from tests.conftest import redirect_sase_home


def _mock_patch(status: str = "Draft") -> MagicMock:
    patch = MagicMock()
    patch.name = "my_feature"
    patch.file_path = "/path/to/project.sase"
    patch.pr_url = "http://cl/123456"
    patch.status = status
    patch.comments = None
    return patch


def test_extract_change_identifier_valid_https() -> None:
    """Test extracting PR number from https URL via workspace provider plugin."""
    with patch_ctx(
        "sase.workspace_provider.extract_change_identifier",
        return_value=("987654321", "hg"),
    ):
        result = _extract_change_identifier("https://cl/987654321")
    assert result == ("987654321", "hg")


def test_extract_change_identifier_invalid_url() -> None:
    """Test that invalid URLs return None."""
    with patch_ctx(
        "sase.workspace_provider.extract_change_identifier",
        return_value=None,
    ):
        assert _extract_change_identifier("not-a-url") is None
        assert _extract_change_identifier("http://example.com/123") is None
    assert _extract_change_identifier("") is None


def test_parse_check_completion_missing_file() -> None:
    """Test that missing file returns not complete."""
    is_complete, exit_code, content = _parse_check_completion("/nonexistent/path.txt")
    assert is_complete is False
    assert exit_code == -1
    assert content == ""


def test_parse_check_completion_malformed_marker() -> None:
    """Test parsing output with malformed completion marker."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        f.write("Output\n")
        f.write(f"{CHECK_COMPLETE_MARKER}MALFORMED\n")
        temp_path = f.name

    try:
        is_complete, exit_code, content = _parse_check_completion(temp_path)
        assert is_complete is True
        assert exit_code == 1  # Default to 1 on parse error
    finally:
        os.unlink(temp_path)


def test_get_pending_checks_no_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that missing checks directory returns empty list."""
    mock_patch = MagicMock()
    mock_patch.name = "test_feature"

    redirect_sase_home(monkeypatch, tmp_path)
    result = _get_pending_checks(mock_patch)
    assert result == []


def test_get_pending_checks_with_matching_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test finding pending checks in the checks directory."""
    mock_patch = MagicMock()
    mock_patch.name = "my_feature"

    redirect_sase_home(monkeypatch, tmp_path)
    checks_shard = tmp_path / "checks" / "202412"
    checks_shard.mkdir(parents=True)
    (checks_shard / "my_feature-cl_submitted-241227_120000.txt").touch()
    (checks_shard / "my_feature-reviewer_comments-241227_120001.txt").touch()
    (checks_shard / "other_feature-cl_submitted-241227_120002.txt").touch()

    result = _get_pending_checks(mock_patch)

    # Should find 2 files matching my_feature
    assert len(result) == 2
    check_types = {check.check_type for check in result}
    assert CHECK_TYPE_CL_SUBMITTED in check_types
    assert CHECK_TYPE_REVIEWER_COMMENTS in check_types


def test_has_pending_check_different_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test has_pending_check returns False for different check type."""
    mock_patch = MagicMock()
    mock_patch.name = "my_feature"

    redirect_sase_home(monkeypatch, tmp_path)
    checks_shard = tmp_path / "checks" / "202412"
    checks_shard.mkdir(parents=True)
    (checks_shard / "my_feature-cl_submitted-241227_120000.txt").touch()

    result = has_pending_check(mock_patch, CHECK_TYPE_REVIEWER_COMMENTS)
    assert result is False


def test__check_pending_checks_processes_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that completed checks are processed and cleaned up."""
    mock_patch = MagicMock()
    mock_patch.name = "my_feature"
    mock_patch.file_path = "/path/to/project.sase"
    mock_patch.pr_url = "http://cl/123456"
    mock_patch.status = "Mailed"
    mock_patch.comments = None
    mock_log = MagicMock()

    redirect_sase_home(monkeypatch, tmp_path)
    checks_shard = tmp_path / "checks" / "202412"
    checks_shard.mkdir(parents=True)
    check_file = checks_shard / "my_feature-cl_submitted-241227_120000.txt"
    check_file.write_text(f"Output\n{CHECK_COMPLETE_MARKER}EXIT_CODE: 1\n")

    with patch_ctx("sase.ace.scheduler.checks_runner.update_last_checked"):
        with patch_ctx(
            "sase.ace.scheduler.checks_runner.is_parent_submitted"
        ) as mock_parent:
            mock_parent.return_value = True
            pending = _get_pending_checks(mock_patch)
            process_pending_checks_for(mock_patch, pending, mock_log)

    # The check file should be cleaned up
    assert not check_file.exists()


def test__check_pending_checks_incomplete_not_processed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that incomplete checks are not processed."""
    mock_patch = MagicMock()
    mock_patch.name = "my_feature"
    mock_log = MagicMock()

    redirect_sase_home(monkeypatch, tmp_path)
    checks_shard = tmp_path / "checks" / "202412"
    checks_shard.mkdir(parents=True)
    check_file = checks_shard / "my_feature-cl_submitted-241227_120000.txt"
    check_file.write_text("Still running...\n")

    pending = _get_pending_checks(mock_patch)
    result = process_pending_checks_for(mock_patch, pending, mock_log)

    # The check file should still exist
    assert check_file.exists()
    # No updates should be returned
    assert result == []


def test_check_type_constants() -> None:
    """Test that check type constants have expected values."""
    assert CHECK_TYPE_CL_SUBMITTED == "cl_submitted"
    assert CHECK_TYPE_REVIEWER_COMMENTS == "reviewer_comments"


def test_check_complete_marker() -> None:
    """Test that completion marker has expected value."""
    assert CHECK_COMPLETE_MARKER == "===CHECK_COMPLETE=== "


def test_handle_cl_submitted_completion_archives_closed_non_terminal_spec() -> None:
    """Exit 20 archives a non-terminal Patch and clears sync cache."""
    patch = _mock_patch(status="Draft")
    log = MagicMock()

    with (
        patch_ctx(
            "sase.ace.scheduler.checks_runner.update_last_checked"
        ) as mock_checked,
        patch_ctx(
            "sase.ace.scheduler.checks_runner.transition_patch_status",
            return_value=(True, "Draft", None, []),
        ) as mock_transition,
        patch_ctx("sase.ace.sync_cache.clear_cache_entry") as mock_clear,
        patch_ctx(
            "sase.ace.scheduler.checks_runner.is_parent_submitted"
        ) as mock_parent_submitted,
    ):
        result = _handle_cl_submitted_completion(
            patch,
            SUBMITTED_CHECK_EXIT_CODE_CLOSED,
            log,
        )

    assert result == "Status changed Draft -> Archived"
    mock_checked.assert_called_once_with("my_feature")
    mock_transition.assert_called_once_with(
        "/path/to/project.sase",
        "my_feature",
        "Archived",
        validate=False,
    )
    mock_clear.assert_called_once_with("my_feature")
    mock_parent_submitted.assert_not_called()


@pytest.mark.parametrize(
    "status",
    [
        "Submitted",
        "Archived",
        "Reverted",
        "Submitted (proj_1)",
        "Archived (proj_1)",
        "Reverted (proj_1)",
    ],
)
def test_handle_cl_submitted_completion_closed_terminal_status_is_noop(
    status: str,
) -> None:
    """Exit 20 does not rewrite already-terminal specs."""
    patch = _mock_patch(status=status)
    log = MagicMock()

    with (
        patch_ctx(
            "sase.ace.scheduler.checks_runner.update_last_checked"
        ) as mock_checked,
        patch_ctx(
            "sase.ace.scheduler.checks_runner.transition_patch_status"
        ) as mock_transition,
        patch_ctx(
            "sase.ace.scheduler.checks_runner.is_parent_submitted"
        ) as mock_parent_submitted,
    ):
        result = _handle_cl_submitted_completion(
            patch,
            SUBMITTED_CHECK_EXIT_CODE_CLOSED,
            log,
        )

    assert result is None
    mock_checked.assert_called_once_with("my_feature")
    mock_transition.assert_not_called()
    mock_parent_submitted.assert_not_called()


@pytest.mark.parametrize("exit_code", [1, 2, 19, 21])
def test_handle_cl_submitted_completion_other_nonzero_exit_is_noop(
    exit_code: int,
) -> None:
    """Only the closed-unmerged exit code archives a Patch."""
    patch = _mock_patch(status="Draft")
    log = MagicMock()

    with (
        patch_ctx(
            "sase.ace.scheduler.checks_runner.update_last_checked"
        ) as mock_checked,
        patch_ctx(
            "sase.ace.scheduler.checks_runner.transition_patch_status"
        ) as mock_transition,
        patch_ctx(
            "sase.ace.scheduler.checks_runner.is_parent_submitted"
        ) as mock_parent_submitted,
    ):
        result = _handle_cl_submitted_completion(patch, exit_code, log)

    assert result is None
    mock_checked.assert_called_once_with("my_feature")
    mock_transition.assert_not_called()
    mock_parent_submitted.assert_not_called()


def test_handle_cl_submitted_completion_exit_zero_still_submits() -> None:
    """Exit 0 keeps the existing Submitted transition behavior."""
    patch = _mock_patch(status="Mailed")
    log = MagicMock()

    with (
        patch_ctx(
            "sase.ace.scheduler.checks_runner.update_last_checked"
        ) as mock_checked,
        patch_ctx(
            "sase.ace.scheduler.checks_runner.is_parent_submitted",
            return_value=True,
        ) as mock_parent_submitted,
        patch_ctx(
            "sase.ace.scheduler.checks_runner.transition_patch_status",
            return_value=(True, "Mailed", None, []),
        ) as mock_transition,
        patch_ctx("sase.ace.sync_cache.clear_cache_entry") as mock_clear,
    ):
        result = _handle_cl_submitted_completion(patch, 0, log)

    assert result == "Status changed Mailed -> Submitted"
    mock_checked.assert_called_once_with("my_feature")
    mock_parent_submitted.assert_called_once_with(patch)
    mock_transition.assert_called_once_with(
        "/path/to/project.sase",
        "my_feature",
        "Submitted",
        validate=False,
    )
    mock_clear.assert_called_once_with("my_feature")


def test_process_pending_checks_for_archives_on_closed_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pending-check poll handles the closed-unmerged completion marker."""
    patch = _mock_patch(status="Ready")
    log = MagicMock()

    redirect_sase_home(monkeypatch, tmp_path)
    checks_shard = tmp_path / "checks" / "202412"
    checks_shard.mkdir(parents=True)
    check_file = checks_shard / "my_feature-cl_submitted-241227_120000.txt"
    check_file.write_text(
        f"PR state: CLOSED\n{CHECK_COMPLETE_MARKER}"
        f"EXIT_CODE: {SUBMITTED_CHECK_EXIT_CODE_CLOSED}\n"
    )

    pending = _get_pending_checks(patch)

    with (
        patch_ctx("sase.ace.scheduler.checks_runner.update_last_checked"),
        patch_ctx(
            "sase.ace.scheduler.checks_runner.transition_patch_status",
            return_value=(True, "Ready", None, []),
        ) as mock_transition,
        patch_ctx("sase.ace.sync_cache.clear_cache_entry") as mock_clear,
    ):
        result = process_pending_checks_for(patch, pending, log)

    assert result == ["Status changed Ready -> Archived"]
    mock_transition.assert_called_once_with(
        "/path/to/project.sase",
        "my_feature",
        "Archived",
        validate=False,
    )
    mock_clear.assert_called_once_with("my_feature")
    assert not check_file.exists()


# === Tests for start_reviewer_comments_check git skip ===


def test_start_reviewer_comments_check_skips_for_git() -> None:
    """Test that start_reviewer_comments_check returns None when plugin says unsupported."""
    mock_patch = MagicMock()
    mock_patch.name = "my_feature"
    mock_patch.pr_url = "https://github.com/user/repo/pull/42"
    mock_log = MagicMock()

    with patch_ctx(
        "sase.workspace_provider.supports_reviewer_comments",
        return_value=False,
    ):
        result = start_reviewer_comments_check(mock_patch, "/workspace", mock_log)
    assert result is None


def test_start_reviewer_comments_check_skips_for_no_cl() -> None:
    """Test that start_reviewer_comments_check handles None PR gracefully."""
    mock_patch = MagicMock()
    mock_patch.name = "my_feature"
    mock_patch.pr_url = None
    mock_log = MagicMock()

    # With no CL, the supports_reviewer_comments check is skipped entirely.
    # We mock generate_reviewer_comments_script to return a script body and
    # patch Popen to avoid actually running a command.
    with (
        patch_ctx(
            "sase.workspace_provider.generate_reviewer_comments_script",
            return_value="critique_comments my_feature 2>&1",
        ),
        patch_ctx("sase.ace.scheduler.checks_runner.subprocess.Popen") as mock_popen,
    ):
        mock_popen.return_value = MagicMock()
        result = start_reviewer_comments_check(mock_patch, "/workspace", mock_log)
    # Should attempt to start (for hg repos that might not have a PR URL yet)
    assert result == "Started reviewer_comments check"


# === Tests for orphan reaper and single-scan poll ===


def testreap_orphan_check_files_deletes_old_marker_less(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Old files without a completion marker get reaped."""
    redirect_sase_home(monkeypatch, tmp_path)
    shard = tmp_path / "checks" / "202604"
    shard.mkdir(parents=True)
    orphan = shard / "my_feature-cl_submitted-260423_120000.txt"
    orphan.write_text("")
    old_mtime = time.time() - 300
    os.utime(orphan, (old_mtime, old_mtime))

    log = MagicMock()
    count = reap_orphan_check_files(log)

    assert count == 1
    assert not orphan.exists()
    log.assert_called_once()


def testreap_orphan_check_files_preserves_recent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recent files are not reaped even when missing the completion marker."""
    redirect_sase_home(monkeypatch, tmp_path)
    shard = tmp_path / "checks" / "202604"
    shard.mkdir(parents=True)
    recent = shard / "my_feature-cl_submitted-260423_120000.txt"
    recent.write_text("")

    log = MagicMock()
    count = reap_orphan_check_files(log)

    assert count == 0
    assert recent.exists()


def testreap_orphan_check_files_preserves_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Old files WITH the completion marker are left for the normal poll."""
    redirect_sase_home(monkeypatch, tmp_path)
    shard = tmp_path / "checks" / "202604"
    shard.mkdir(parents=True)
    completed = shard / "my_feature-cl_submitted-260423_120000.txt"
    completed.write_text(f"output\n{CHECK_COMPLETE_MARKER}EXIT_CODE: 0\n")
    old_mtime = time.time() - 300
    os.utime(completed, (old_mtime, old_mtime))

    log = MagicMock()
    count = reap_orphan_check_files(log)

    assert count == 0
    assert completed.exists()


def test_scan_all_pending_checks_groups_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Files from different shards are grouped by safe Patch name."""
    redirect_sase_home(monkeypatch, tmp_path)
    shard_a = tmp_path / "checks" / "202603"
    shard_b = tmp_path / "checks" / "202604"
    shard_a.mkdir(parents=True)
    shard_b.mkdir(parents=True)
    (shard_a / "foo-cl_submitted-260301_120000.txt").touch()
    (shard_b / "foo-reviewer_comments-260423_120000.txt").touch()
    (shard_b / "bar-cl_submitted-260423_130000.txt").touch()

    result = scan_all_pending_checks()

    assert set(result.keys()) == {"foo", "bar"}
    assert len(result["foo"]) == 2
    assert len(result["bar"]) == 1
    assert {c.check_type for c in result["foo"]} == {
        CHECK_TYPE_CL_SUBMITTED,
        CHECK_TYPE_REVIEWER_COMMENTS,
    }


def test_scan_all_pending_checks_ignores_malformed_filenames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Files that don't match the expected filename format are skipped."""
    redirect_sase_home(monkeypatch, tmp_path)
    shard = tmp_path / "checks" / "202604"
    shard.mkdir(parents=True)
    (shard / "nonsense.txt").touch()
    (shard / "foo-badtype-260423_120000.txt").touch()
    (shard / "foo-cl_submitted-260423_120000.txt").touch()

    result = scan_all_pending_checks()

    assert set(result.keys()) == {"foo"}
    assert len(result["foo"]) == 1
    assert result["foo"][0].check_type == CHECK_TYPE_CL_SUBMITTED


def test_run_pending_checks_poll_scans_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The poll walks the checks directory once regardless of Patch count."""
    from sase.axe.hook_jobs import HookJobRunner
    from sase.axe.state import AxeMetrics

    redirect_sase_home(monkeypatch, tmp_path)

    specs = []
    for i in range(5):
        cs = MagicMock()
        cs.name = f"feature_{i}"
        specs.append(cs)

    runner = HookJobRunner(
        metrics=AxeMetrics(),
        zombie_timeout_seconds=60,
        max_hook_runners=4,
        max_agent_runners=4,
        log_callback=MagicMock(),
    )

    with patch_ctx(
        "sase.ace.scheduler.checks_runner.iter_sharded_files",
        return_value=iter([]),
    ) as mock_iter:
        runner.run_pending_checks_poll(specs)

    # One call for the reaper, one call for scan_all_pending_checks.
    # Crucially, NOT one-per-Patch.
    assert mock_iter.call_count == 2
