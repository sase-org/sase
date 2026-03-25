"""Tests for sase.ace.archive module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.ace.archive import archive_changespec


def test_archive_changespec_fails_without_cl(make_changespec) -> None:  # type: ignore[no-untyped-def]
    """Test archive_changespec fails when CL is not set."""
    changespec = make_changespec.create_with_file(cl=None)

    success, error = archive_changespec(changespec)

    assert success is False
    assert error == "ChangeSpec does not have a valid CL set"
    Path(changespec.file_path).unlink()


def test_archive_changespec_fails_with_non_terminal_children(make_changespec) -> None:  # type: ignore[no-untyped-def]
    """Test archive_changespec fails when ChangeSpec has non-terminal children."""
    parent = make_changespec.create_with_file(name="parent_feature")
    child = make_changespec.create_with_file(
        name="child_feature", parent="parent_feature", status="Draft"
    )

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.archive.return_value = (True, None)

    with patch("sase.ace.archive.find_all_changespecs", return_value=[parent, child]):
        with patch(
            "sase.ace.archive.get_first_available_axe_workspace", return_value=100
        ):
            with patch(
                "sase.ace.archive.get_workspace_directory_for_num",
                return_value=("/tmp", None),
            ):
                with patch("sase.ace.archive.claim_workspace", return_value=True):
                    with patch(
                        "sase.ace.archive.get_vcs_provider", return_value=mock_provider
                    ):
                        with patch("sase.ace.archive.release_workspace"):
                            success, error = archive_changespec(parent)

    assert success is False
    assert error is not None
    assert "Cannot archive" in error
    assert "not Archived or Reverted" in error

    Path(parent.file_path).unlink()
    Path(child.file_path).unlink()


def test_archive_changespec_claims_workspace_100_plus(make_changespec) -> None:  # type: ignore[no-untyped-def]
    """Test archive_changespec claims workspace in >=100 range."""
    changespec = make_changespec.create_with_file()
    console = MagicMock()

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.abandon_change.return_value = (True, None)
    mock_provider.archive.return_value = (True, None)

    with patch("sase.ace.archive.find_all_changespecs", return_value=[changespec]):
        with patch(
            "sase.ace.archive.get_first_available_axe_workspace", return_value=100
        ) as mock_get_ws:
            with patch(
                "sase.ace.archive.get_workspace_directory_for_num",
                return_value=("/tmp", None),
            ):
                with patch(
                    "sase.ace.archive.claim_workspace", return_value=True
                ) as mock_claim:
                    with patch(
                        "sase.ace.archive.get_vcs_provider", return_value=mock_provider
                    ):
                        with patch(
                            "sase.ace.archive.save_diff_to_file",
                            return_value=(True, None),
                        ):
                            with patch(
                                "sase.ace.archive.rename_changespec_with_references"
                            ):
                                with patch(
                                    "sase.ace.archive.transition_changespec_status",
                                    return_value=(True, "Mailed", None, []),
                                ):
                                    with patch("sase.ace.archive.release_workspace"):
                                        success, _error = archive_changespec(
                                            changespec, console
                                        )

    assert success is True
    mock_get_ws.assert_called_once_with(changespec.file_path)
    # Verify claim_workspace was called with workspace_num >= 100
    mock_claim.assert_called_once()
    call_args = mock_claim.call_args
    assert call_args[0][1] == 100  # workspace_num argument

    Path(changespec.file_path).unlink()


def test_archive_changespec_fails_on_archive_error(make_changespec) -> None:  # type: ignore[no-untyped-def]
    """Test archive_changespec fails when sase_hg_archive fails."""
    changespec = make_changespec.create_with_file()

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.abandon_change.return_value = (True, None)
    mock_provider.archive.return_value = (False, "archive failed")

    with patch("sase.ace.archive.find_all_changespecs", return_value=[changespec]):
        with patch(
            "sase.ace.archive.get_first_available_axe_workspace", return_value=100
        ):
            with patch(
                "sase.ace.archive.get_workspace_directory_for_num",
                return_value=("/tmp", None),
            ):
                with patch("sase.ace.archive.claim_workspace", return_value=True):
                    with patch(
                        "sase.ace.archive.get_vcs_provider", return_value=mock_provider
                    ):
                        with patch(
                            "sase.ace.archive.save_diff_to_file",
                            return_value=(True, None),
                        ):
                            with patch("sase.ace.archive.release_workspace"):
                                success, error = archive_changespec(changespec)

    assert success is False
    assert error is not None
    assert "Failed to archive revision" in error

    Path(changespec.file_path).unlink()


def test_archive_changespec_releases_workspace_on_failure(make_changespec) -> None:  # type: ignore[no-untyped-def]
    """Test archive_changespec releases workspace even on failure."""
    changespec = make_changespec.create_with_file()

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (False, "update failed")

    with patch("sase.ace.archive.find_all_changespecs", return_value=[changespec]):
        with patch(
            "sase.ace.archive.get_first_available_axe_workspace", return_value=100
        ):
            with patch(
                "sase.ace.archive.get_workspace_directory_for_num",
                return_value=("/tmp", None),
            ):
                with patch("sase.ace.archive.claim_workspace", return_value=True):
                    with patch(
                        "sase.ace.archive.get_vcs_provider", return_value=mock_provider
                    ):
                        with patch(
                            "sase.ace.archive.release_workspace"
                        ) as mock_release:
                            success, error = archive_changespec(changespec)

    assert success is False
    assert error is not None
    assert "Failed to checkout CL" in error
    mock_release.assert_called_once()

    Path(changespec.file_path).unlink()
