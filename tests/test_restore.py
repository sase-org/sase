"""Tests for the restore module."""

from unittest.mock import MagicMock, patch

from sase.ace.restore import (
    list_reverted_changespecs,
    restore_changespec,
)


def test_list_reverted_changespecs(make_changespec) -> None:  # type: ignore[no-untyped-def]
    """Test list_reverted_changespecs filters by Reverted status."""
    reverted_cs = make_changespec.create(
        name="test_project_feature__1", status="Reverted"
    )
    mailed_cs = make_changespec.create(name="other__1", status="Mailed")
    submitted_cs = make_changespec.create(name="submitted__1", status="Submitted")

    with patch(
        "sase.ace.restore.find_all_changespecs",
        return_value=[reverted_cs, mailed_cs, submitted_cs],
    ):
        result = list_reverted_changespecs()

    assert len(result) == 1
    assert result[0].name == "test_project_feature__1"
    assert result[0].status == "Reverted"


def test_restore_changespec_wrong_status(make_changespec) -> None:  # type: ignore[no-untyped-def]
    """Test restore_changespec fails if status is not Reverted."""
    changespec = make_changespec.create(name="test_project_feature__1", status="Mailed")

    success, error = restore_changespec(changespec)

    assert success is False
    assert error is not None
    assert "not 'Reverted'" in error


def test_restore_changespec_no_workspace_dir(make_changespec) -> None:  # type: ignore[no-untyped-def]
    """Test restore_changespec fails if workspace directory not determined."""
    changespec = make_changespec.create(
        name="test_project_feature__1", status="Reverted"
    )

    with patch(
        "sase.ace.restore.get_workspace_directory_for_changespec", return_value=None
    ):
        success, error = restore_changespec(changespec)

    assert success is False
    assert error is not None
    assert "Could not determine workspace directory" in error


def test_restore_changespec_workspace_not_exists(make_changespec) -> None:  # type: ignore[no-untyped-def]
    """Test restore_changespec fails if workspace directory doesn't exist."""
    changespec = make_changespec.create(
        name="test_project_feature__1", status="Reverted"
    )

    with patch(
        "sase.ace.restore.get_workspace_directory_for_changespec",
        return_value="/nonexistent/path",
    ):
        success, error = restore_changespec(changespec)

    assert success is False
    assert error is not None
    assert "does not exist" in error


def test_restore_changespec_success(make_changespec) -> None:  # type: ignore[no-untyped-def]
    """Test restore_changespec succeeds with all requirements met."""
    changespec = make_changespec.create(
        name="test_project_feature__1", status="Reverted"
    )
    console = MagicMock()

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.apply_patch.return_value = (True, None)

    with patch(
        "sase.ace.restore.get_workspace_directory_for_changespec", return_value="/tmp"
    ):
        with patch("os.path.isdir", return_value=True):
            with patch("sase.ace.restore.update_changespec_name_atomic") as mock_rename:
                with patch(
                    "sase.ace.restore.get_vcs_provider", return_value=mock_provider
                ):
                    with patch(
                        "sase.ace.restore.run_workspace_command",
                        return_value=(True, None),
                    ):
                        with patch("pathlib.Path.exists", return_value=True):
                            success, error = restore_changespec(changespec, console)

    assert success is True
    assert error is None
    mock_rename.assert_called_once_with(
        changespec.file_path, "test_project_feature__1", "test_project_feature"
    )


def test_restore_changespec_with_parent(make_changespec) -> None:  # type: ignore[no-untyped-def]
    """Test restore_changespec uses parent for sase_hg_update."""
    changespec = make_changespec.create(
        name="test_project_feature__1", status="Reverted", parent="parent_branch"
    )

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.apply_patch.return_value = (True, None)
    mock_provider.resolve_revision.return_value = "parent_branch"

    with patch(
        "sase.ace.restore.get_workspace_directory_for_changespec", return_value="/tmp"
    ):
        with patch("os.path.isdir", return_value=True):
            with patch("sase.ace.restore.update_changespec_name_atomic"):
                with patch(
                    "sase.ace.restore.get_vcs_provider", return_value=mock_provider
                ):
                    with patch(
                        "sase.ace.restore.run_workspace_command",
                        return_value=(True, None),
                    ):
                        with patch("pathlib.Path.exists", return_value=True):
                            restore_changespec(changespec)

    # Provider should resolve and then checkout with parent
    mock_provider.resolve_revision.assert_called_once()
    mock_provider.checkout.assert_called_once_with("parent_branch", "/tmp")


def test_restore_changespec_sase_hg_update_fails(make_changespec) -> None:  # type: ignore[no-untyped-def]
    """Test restore_changespec fails when sase_hg_update fails."""
    changespec = make_changespec.create(
        name="test_project_feature__1", status="Reverted"
    )

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (False, "update failed")

    with patch(
        "sase.ace.restore.get_workspace_directory_for_changespec", return_value="/tmp"
    ):
        with patch("os.path.isdir", return_value=True):
            with patch("sase.ace.restore.update_changespec_name_atomic"):
                with patch(
                    "sase.ace.restore.get_vcs_provider", return_value=mock_provider
                ):
                    success, error = restore_changespec(changespec)

    assert success is False
    assert error == "update failed"


def test_restore_changespec_diff_not_found(make_changespec) -> None:  # type: ignore[no-untyped-def]
    """Test restore_changespec fails when diff file not found."""
    changespec = make_changespec.create(
        name="test_project_feature__1", status="Reverted"
    )

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)

    with patch(
        "sase.ace.restore.get_workspace_directory_for_changespec", return_value="/tmp"
    ):
        with patch("os.path.isdir", return_value=True):
            with patch("sase.ace.restore.update_changespec_name_atomic"):
                with patch(
                    "sase.ace.restore.get_vcs_provider", return_value=mock_provider
                ):
                    with patch("pathlib.Path.exists", return_value=False):
                        success, error = restore_changespec(changespec)

    assert success is False
    assert error is not None
    assert "Diff file not found" in error


def test_restore_changespec_hg_import_fails(make_changespec) -> None:  # type: ignore[no-untyped-def]
    """Test restore_changespec fails when hg import fails."""
    changespec = make_changespec.create(
        name="test_project_feature__1", status="Reverted"
    )

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.apply_patch.return_value = (False, "hg failed: import failed")

    with patch(
        "sase.ace.restore.get_workspace_directory_for_changespec", return_value="/tmp"
    ):
        with patch("os.path.isdir", return_value=True):
            with patch("sase.ace.restore.update_changespec_name_atomic"):
                with patch(
                    "sase.ace.restore.get_vcs_provider", return_value=mock_provider
                ):
                    with patch("pathlib.Path.exists", return_value=True):
                        success, error = restore_changespec(changespec)

    assert success is False
    assert error is not None
    assert "import failed" in error


def test_restore_changespec_sase_commit_fails(make_changespec) -> None:  # type: ignore[no-untyped-def]
    """Test restore_changespec fails when sase commit fails."""
    changespec = make_changespec.create(
        name="test_project_feature__1", status="Reverted"
    )

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.apply_patch.return_value = (True, None)

    with patch(
        "sase.ace.restore.get_workspace_directory_for_changespec", return_value="/tmp"
    ):
        with patch("os.path.isdir", return_value=True):
            with patch("sase.ace.restore.update_changespec_name_atomic"):
                with patch(
                    "sase.ace.restore.get_vcs_provider", return_value=mock_provider
                ):
                    with patch(
                        "sase.ace.restore.run_workspace_command",
                        return_value=(False, "sase failed: commit failed"),
                    ):
                        with patch("pathlib.Path.exists", return_value=True):
                            success, error = restore_changespec(changespec)

    assert success is False
    assert error is not None
    assert "commit failed" in error
