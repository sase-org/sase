"""Tests for the ace TUI keybinding footer workflow and rebase bindings."""

from unittest.mock import patch as mock_patch

from sase.ace.patch import Patch, CommentEntry
from sase.ace.tui.widgets import KeybindingFooter


def _make_patch(
    name: str = "test_feature",
    description: str = "Test description",
    status: str = "Ready",
    cl: str | None = None,
    parent: str | None = None,
    file_path: str = "/tmp/test.sase",
    comments: list[CommentEntry] | None = None,
) -> Patch:
    """Create a mock Patch for testing."""
    return Patch(
        name=name,
        description=description,
        parent=parent,
        cl=cl,
        status=status,
        file_path=file_path,
        line_number=1,
        commits=None,
        hooks=None,
        comments=comments,
    )


# --- Rebase Binding Tests ---


# --- Workflow Binding Tests ---


def test_keybinding_footer_workflow_binding_single() -> None:
    """Test 'r' (run) binding shows workflow name when one workflow available."""
    footer = KeybindingFooter()
    # Create a patch with a fix-hook comment to trigger workflow
    comment = CommentEntry(
        reviewer="fix-hook",
        file_path="test.py",
    )
    patch = _make_patch(status="Ready", comments=[comment])

    with mock_patch(
        "sase.ace.tui.widgets._keybinding_bindings.get_available_workflows"
    ) as mock:
        mock.return_value = ["fix"]
        bindings = footer._compute_available_bindings(patch)

    binding_dict = dict(bindings)
    assert "r" in binding_dict
    assert "fix" in binding_dict["r"]


def test_keybinding_footer_workflow_binding_multiple() -> None:
    """Test 'r' (run) binding shows count when multiple workflows available."""
    footer = KeybindingFooter()
    patch = _make_patch(status="Ready")

    with mock_patch(
        "sase.ace.tui.widgets._keybinding_bindings.get_available_workflows"
    ) as mock:
        mock.return_value = ["fix", "crs"]
        bindings = footer._compute_available_bindings(patch)

    binding_dict = dict(bindings)
    assert "r" in binding_dict
    assert "2 workflows" in binding_dict["r"]


# --- Edit, Copy, Fold Binding Tests ---
