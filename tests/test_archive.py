"""Tests for sase.ace.archive module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.ace.archive import archive_patch


def test_archive_patch_fails_without_pr(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test archive_patch fails when PR is not set."""
    patch_record = make_patch.create_with_file(cl=None)

    success, error = archive_patch(patch_record)

    assert success is False
    assert error == "Patch does not have a valid PR set"
    Path(patch_record.file_path).unlink()


def test_archive_patch_fails_with_non_terminal_children(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test archive_patch fails when Patch has non-terminal children."""
    parent = make_patch.create_with_file(name="parent_feature")
    child = make_patch.create_with_file(
        name="child_feature", parent="parent_feature", status="Draft"
    )

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.archive.return_value = (True, None)

    with patch("sase.ace.archive.find_all_patches", return_value=[parent, child]):
        success, error = archive_patch(parent)

    assert success is False
    assert error is not None
    assert "Cannot archive" in error
    assert "not Archived or Reverted" in error

    Path(parent.file_path).unlink()
    Path(child.file_path).unlink()


def test_archive_patch_claims_workspace_100_plus(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test archive_patch claims workspace in >=100 range."""
    patch_record = make_patch.create_with_file()
    console = MagicMock()

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.abandon_change.return_value = (True, None)
    mock_provider.archive.return_value = (True, None)

    with patch("sase.ace.archive.find_all_patches", return_value=[patch_record]):
        with patch(
            "sase.ace.archive.claim_next_axe_workspace_dir",
            return_value=(100, "/tmp", None),
        ) as mock_claim:
            with patch("sase.ace.archive.get_vcs_provider", return_value=mock_provider):
                with patch(
                    "sase.ace.archive.save_diff_to_file",
                    return_value=(True, None),
                ):
                    with patch("sase.ace.archive.rename_patch_with_references"):
                        with patch(
                            "sase.ace.archive.transition_patch_status",
                            return_value=(True, "Mailed", None, []),
                        ):
                            with patch("sase.ace.archive.release_workspace"):
                                success, _error = archive_patch(patch_record, console)

    assert success is True
    mock_claim.assert_called_once()
    assert mock_claim.call_args.args[0] == patch_record.file_path

    Path(patch_record.file_path).unlink()


def test_archive_patch_fails_on_archive_error(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test archive_patch fails when sase_hg_archive fails."""
    patch_record = make_patch.create_with_file()

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.abandon_change.return_value = (True, None)
    mock_provider.archive.return_value = (False, "archive failed")

    with patch("sase.ace.archive.find_all_patches", return_value=[patch_record]):
        with patch(
            "sase.ace.archive.claim_next_axe_workspace_dir",
            return_value=(100, "/tmp", None),
        ):
            with patch("sase.ace.archive.get_vcs_provider", return_value=mock_provider):
                with patch(
                    "sase.ace.archive.save_diff_to_file",
                    return_value=(True, None),
                ):
                    with patch("sase.ace.archive.release_workspace"):
                        success, error = archive_patch(patch_record)

    assert success is False
    assert error is not None
    assert "Failed to archive revision" in error

    Path(patch_record.file_path).unlink()


def test_archive_patch_releases_workspace_on_failure(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test archive_patch releases workspace even on failure."""
    patch_record = make_patch.create_with_file()

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (False, "update failed")

    with patch("sase.ace.archive.find_all_patches", return_value=[patch_record]):
        with patch(
            "sase.ace.archive.claim_next_axe_workspace_dir",
            return_value=(100, "/tmp", None),
        ):
            with patch("sase.ace.archive.get_vcs_provider", return_value=mock_provider):
                with patch("sase.ace.archive.release_workspace") as mock_release:
                    success, error = archive_patch(patch_record)

    assert success is False
    assert error is not None
    assert "Failed to checkout Patch branch" in error
    mock_release.assert_called_once()

    Path(patch_record.file_path).unlink()
