"""Tests for sase.work.revert module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.ace.revert import (
    revert_patch,
)


def test_revert_patch_succeeds_without_cl(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test revert_patch succeeds without a CL, skipping VCS operations."""
    patch_record = make_patch.create_with_file(cl=None)

    with patch("sase.ace.revert.find_all_patches", return_value=[patch_record]):
        with patch(
            "sase.ace.revert.transition_patch_status",
            return_value=(True, "Draft", None, []),
        ):
            # The implementation still exercises this legacy compatibility alias.
            with patch(
                "sase.ace.revert.rename_changespec_with_references"
                # legacy compatibility alias
            ) as mock_rename:
                with patch("sase.ace.revert.save_diff_to_file") as mock_save_diff:
                    with patch("sase.ace.revert.get_vcs_provider") as mock_get_vcs:
                        # The implementation still exercises this legacy alias.
                        with patch(
                            "sase.ace.revert.reset_changespec_pr_url"
                            # legacy compatibility alias
                        ) as mock_reset_cl:
                            success, error = revert_patch(patch_record)

    assert success is True
    assert error is None
    # VCS operations should NOT be called when PR is None
    mock_save_diff.assert_not_called()
    mock_get_vcs.assert_not_called()
    mock_reset_cl.assert_not_called()
    # Rename and status transition should still be called
    mock_rename.assert_called_once()

    Path(patch_record.file_path).unlink()


def test_revert_patch_fails_with_children(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test revert_patch fails when Patch has children."""
    parent = make_patch.create_with_file(name="parent_feature")
    child = make_patch.create_with_file(name="child_feature", parent="parent_feature")

    with patch("sase.ace.revert.find_all_patches", return_value=[parent, child]):
        success, error = revert_patch(parent)

    assert success is False
    assert error is not None
    assert "Cannot revert: other Patches have this one as their parent" in error

    Path(parent.file_path).unlink()
    Path(child.file_path).unlink()


def test_revert_patch_fails_without_workspace_dir(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test revert_patch fails when workspace directory cannot be determined."""
    patch_record = make_patch.create_with_file()

    with patch("sase.ace.revert.find_all_patches", return_value=[patch_record]):
        with patch.dict("os.environ", {}, clear=True):
            success, error = revert_patch(patch_record)

    assert success is False
    assert error is not None
    assert "Could not determine workspace directory" in error

    Path(patch_record.file_path).unlink()


def test_revert_patch_fails_with_nonexistent_workspace(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test revert_patch fails when workspace directory doesn't exist."""
    patch_record = make_patch.create_with_file()

    with patch("sase.ace.revert.find_all_patches", return_value=[patch_record]):
        with patch("sase.ace.revert.get_workspace_directory_for_patch") as mock_get_ws:
            mock_get_ws.return_value = "/nonexistent/workspace"
            success, error = revert_patch(patch_record)

    assert success is False
    assert error is not None
    assert "Workspace directory does not exist" in error

    Path(patch_record.file_path).unlink()


def test_revert_patch_success(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test revert_patch succeeds with all requirements met."""
    patch_record = make_patch.create_with_file()
    console = MagicMock()

    mock_provider = MagicMock()
    mock_provider.abandon_change.return_value = (True, None)
    mock_provider.prune.return_value = (True, None)

    with patch("sase.ace.revert.find_all_patches", return_value=[patch_record]):
        with patch(
            "sase.ace.revert.get_workspace_directory_for_patch",
            return_value="/tmp",
        ):
            with patch("sase.ace.revert.save_diff_to_file", return_value=(True, None)):
                with patch(
                    "sase.ace.revert.get_vcs_provider", return_value=mock_provider
                ):
                    # The implementation still exercises this legacy compatibility alias.
                    with patch(
                        "sase.ace.revert.rename_changespec_with_references"
                        # legacy compatibility alias
                    ) as mock_rename:
                        with patch(
                            "sase.ace.revert.transition_patch_status",
                            return_value=(True, "Mailed", None, []),
                        ):
                            # The implementation still exercises this legacy alias.
                            with patch("sase.ace.revert.reset_changespec_pr_url"):
                                success, error = revert_patch(patch_record, console)

    assert success is True
    assert error is None
    mock_rename.assert_called_once()

    Path(patch_record.file_path).unlink()


def test_revert_patch_fails_on_diff_error(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test revert_patch fails when diff cannot be saved."""
    patch_record = make_patch.create_with_file()

    with patch("sase.ace.revert.find_all_patches", return_value=[patch_record]):
        with patch(
            "sase.ace.revert.get_workspace_directory_for_patch",
            return_value="/tmp",
        ):
            with patch(
                "sase.ace.revert.save_diff_to_file",
                return_value=(False, "hg diff failed"),
            ):
                success, error = revert_patch(patch_record)

    assert success is False
    assert error is not None
    assert "Failed to save diff" in error

    Path(patch_record.file_path).unlink()


def test_revert_patch_fails_on_prune_error(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test revert_patch fails when prune fails."""
    patch_record = make_patch.create_with_file()

    mock_provider = MagicMock()
    mock_provider.abandon_change.return_value = (True, None)
    mock_provider.prune.return_value = (False, "prune failed")

    with patch("sase.ace.revert.find_all_patches", return_value=[patch_record]):
        with patch(
            "sase.ace.revert.get_workspace_directory_for_patch",
            return_value="/tmp",
        ):
            with patch("sase.ace.revert.save_diff_to_file", return_value=(True, None)):
                with patch(
                    "sase.ace.revert.get_vcs_provider", return_value=mock_provider
                ):
                    success, error = revert_patch(patch_record)

    assert success is False
    assert error is not None
    assert "Failed to prune revision" in error

    Path(patch_record.file_path).unlink()


def test_revert_patch_calls_kill_and_persist(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test revert_patch calls kill_and_persist_all_running_processes."""
    patch_record = make_patch.create_with_file()

    mock_provider = MagicMock()
    mock_provider.abandon_change.return_value = (True, None)
    mock_provider.prune.return_value = (True, None)

    with patch("sase.ace.revert.find_all_patches", return_value=[patch_record]):
        with patch(
            "sase.ace.revert.get_workspace_directory_for_patch",
            return_value="/tmp",
        ):
            with patch("sase.ace.revert.save_diff_to_file", return_value=(True, None)):
                with patch(
                    "sase.ace.revert.get_vcs_provider", return_value=mock_provider
                ):
                    # The implementation still exercises this legacy compatibility alias.
                    with patch("sase.ace.revert.rename_changespec_with_references"):
                        with patch(
                            "sase.ace.revert.transition_patch_status",
                            return_value=(True, "Mailed", None, []),
                        ):
                            # The implementation still exercises this legacy alias.
                            with patch("sase.ace.revert.reset_changespec_pr_url"):
                                with patch(
                                    "sase.ace.revert.kill_and_persist_all_running_processes"
                                ) as mock_kill:
                                    success, _error = revert_patch(patch_record)

    assert success is True
    mock_kill.assert_called_once()
    call_args = mock_kill.call_args
    assert call_args[0][0] is patch_record  # patch_record
    assert call_args[0][1] == patch_record.file_path  # project_file
    assert call_args[0][2] == patch_record.name  # cl_name
    assert "reverted" in call_args[0][3].lower()  # kill_reason

    Path(patch_record.file_path).unlink()
