"""Tests for update_to_patch operations."""

from unittest.mock import MagicMock, patch as mock_patch

from sase.ace.operations import (
    update_to_changespec as update_to_patch,  # legacy ACE API name
)
from sase.ace.patch import Patch


def _make_patch(**kwargs: object) -> Patch:
    """Create a Patch with sensible defaults for testing."""
    defaults: dict[str, object] = {
        "name": "test_feature",
        "description": "Test",
        "parent": None,
        "cl": None,
        "status": "Ready",
        "file_path": "/path/to/project.sase",
        "line_number": 1,
    }
    defaults.update(kwargs)
    return Patch(**defaults)  # type: ignore[arg-type]


def test_update_to_patch_with_revision() -> None:
    """Test that update_to_patch uses provided revision when specified."""
    patch = _make_patch(parent="parent_cl_123", cl="cl_456")

    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.resolve_revision.side_effect = lambda name, *_: name

    with mock_patch(
        "sase.ace.operations.get_workspace_dir_from_project"
    ) as mock_get_ws:
        mock_get_ws.return_value = "/tmp/project/src"
        with mock_patch("os.path.exists", return_value=True):
            with mock_patch("os.path.isdir", return_value=True):
                with mock_patch(
                    "sase.vcs_provider.get_vcs_provider", return_value=mock_provider
                ):
                    success, error = update_to_patch(patch, revision="custom_revision")

    assert success is True
    assert error is None
    mock_provider.checkout.assert_called_once_with(
        "custom_revision", "/tmp/project/src"
    )
