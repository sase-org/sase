"""Tests for the restore module."""

from unittest.mock import MagicMock, patch as mock_patch

from sase.ace.restore import (
    list_reverted_patches,
    restore_patch,
)


def test_list_reverted_patches(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test list_reverted_patches filters by Reverted status."""
    reverted_cs = make_patch.create(name="test_project_feature__1", status="Reverted")
    mailed_cs = make_patch.create(name="other__1", status="Mailed")
    submitted_cs = make_patch.create(name="submitted__1", status="Submitted")

    with mock_patch(
        "sase.ace.restore.find_all_patches",
        return_value=[reverted_cs, mailed_cs, submitted_cs],
    ):
        result = list_reverted_patches()

    assert len(result) == 1
    assert result[0].name == "test_project_feature__1"
    assert result[0].status == "Reverted"


def test_restore_patch_wrong_status(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test restore_patch fails if status is not Reverted."""
    patch = make_patch.create(name="test_project_feature__1", status="Mailed")

    success, error = restore_patch(patch)

    assert success is False
    assert error is not None
    assert "not 'Reverted'" in error


def test_restore_patch_no_workspace_dir(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test restore_patch fails if workspace directory not determined."""
    patch = make_patch.create(name="test_project_feature__1", status="Reverted")

    with mock_patch(
        "sase.ace.restore.get_workspace_directory_for_patch", return_value=None
    ):
        success, error = restore_patch(patch)

    assert success is False
    assert error is not None
    assert "Could not determine workspace directory" in error


def test_restore_patch_workspace_not_exists(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test restore_patch fails if workspace directory doesn't exist."""
    patch = make_patch.create(name="test_project_feature__1", status="Reverted")

    with mock_patch(
        "sase.ace.restore.get_workspace_directory_for_patch",
        return_value="/nonexistent/path",
    ):
        success, error = restore_patch(patch)

    assert success is False
    assert error is not None
    assert "does not exist" in error


def test_restore_patch_success(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test restore_patch succeeds with all requirements met."""
    patch = make_patch.create(name="test_project_feature__1", status="Reverted")
    console = MagicMock()

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.apply_patch.return_value = (True, None)

    with mock_patch(
        "sase.ace.restore.get_workspace_directory_for_patch", return_value="/tmp"
    ):
        with mock_patch("os.path.isdir", return_value=True):
            with mock_patch(
                "sase.ace.restore.update_changespec_name_atomic"
            ) as mock_rename:
                with mock_patch(
                    "sase.ace.restore.get_vcs_provider", return_value=mock_provider
                ):
                    with mock_patch(
                        "sase.ace.restore.run_workspace_command",
                        return_value=(True, None),
                    ):
                        with mock_patch("pathlib.Path.exists", return_value=True):
                            success, error = restore_patch(patch, console)

    assert success is True
    assert error is None
    mock_rename.assert_called_once_with(
        patch.file_path, "test_project_feature__1", "test_project_feature"
    )


def test_restore_patch_with_parent(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test restore_patch uses parent for sase_hg_update."""
    patch = make_patch.create(
        name="test_project_feature__1", status="Reverted", parent="parent_branch"
    )

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.apply_patch.return_value = (True, None)
    mock_provider.resolve_revision.return_value = "parent_branch"

    with mock_patch(
        "sase.ace.restore.get_workspace_directory_for_patch", return_value="/tmp"
    ):
        with mock_patch("os.path.isdir", return_value=True):
            with mock_patch("sase.ace.restore.update_changespec_name_atomic"):
                with mock_patch(
                    "sase.ace.restore.get_vcs_provider", return_value=mock_provider
                ):
                    with mock_patch(
                        "sase.ace.restore.run_workspace_command",
                        return_value=(True, None),
                    ):
                        with mock_patch("pathlib.Path.exists", return_value=True):
                            restore_patch(patch)

    # Provider should resolve and then checkout with parent
    mock_provider.resolve_revision.assert_called_once()
    mock_provider.checkout.assert_called_once_with("parent_branch", "/tmp")


def test_restore_patch_sase_hg_update_fails(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test restore_patch fails when sase_hg_update fails."""
    patch = make_patch.create(name="test_project_feature__1", status="Reverted")

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (False, "update failed")

    with mock_patch(
        "sase.ace.restore.get_workspace_directory_for_patch", return_value="/tmp"
    ):
        with mock_patch("os.path.isdir", return_value=True):
            with mock_patch("sase.ace.restore.update_changespec_name_atomic"):
                with mock_patch(
                    "sase.ace.restore.get_vcs_provider", return_value=mock_provider
                ):
                    success, error = restore_patch(patch)

    assert success is False
    assert error == "update failed"


def test_restore_patch_diff_not_found(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test restore_patch fails when diff file not found."""
    patch = make_patch.create(name="test_project_feature__1", status="Reverted")

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)

    with mock_patch(
        "sase.ace.restore.get_workspace_directory_for_patch", return_value="/tmp"
    ):
        with mock_patch("os.path.isdir", return_value=True):
            with mock_patch("sase.ace.restore.update_changespec_name_atomic"):
                with mock_patch(
                    "sase.ace.restore.get_vcs_provider", return_value=mock_provider
                ):
                    with mock_patch("pathlib.Path.exists", return_value=False):
                        success, error = restore_patch(patch)

    assert success is False
    assert error is not None
    assert "Diff file not found" in error


def test_restore_patch_hg_import_fails(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test restore_patch fails when hg import fails."""
    patch = make_patch.create(name="test_project_feature__1", status="Reverted")

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.apply_patch.return_value = (False, "hg failed: import failed")

    with mock_patch(
        "sase.ace.restore.get_workspace_directory_for_patch", return_value="/tmp"
    ):
        with mock_patch("os.path.isdir", return_value=True):
            with mock_patch("sase.ace.restore.update_changespec_name_atomic"):
                with mock_patch(
                    "sase.ace.restore.get_vcs_provider", return_value=mock_provider
                ):
                    with mock_patch("pathlib.Path.exists", return_value=True):
                        success, error = restore_patch(patch)

    assert success is False
    assert error is not None
    assert "import failed" in error


def test_restore_patch_sase_commit_fails(make_patch) -> None:  # type: ignore[no-untyped-def]
    """Test restore_patch fails when sase commit fails."""
    patch = make_patch.create(name="test_project_feature__1", status="Reverted")

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.apply_patch.return_value = (True, None)

    with mock_patch(
        "sase.ace.restore.get_workspace_directory_for_patch", return_value="/tmp"
    ):
        with mock_patch("os.path.isdir", return_value=True):
            with mock_patch("sase.ace.restore.update_changespec_name_atomic"):
                with mock_patch(
                    "sase.ace.restore.get_vcs_provider", return_value=mock_provider
                ):
                    with mock_patch(
                        "sase.ace.restore.run_workspace_command",
                        return_value=(False, "sase failed: commit failed"),
                    ):
                        with mock_patch("pathlib.Path.exists", return_value=True):
                            success, error = restore_patch(patch)

    assert success is False
    assert error is not None
    assert "commit failed" in error
