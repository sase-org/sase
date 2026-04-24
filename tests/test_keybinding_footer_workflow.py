"""Tests for the ace TUI keybinding footer workflow and rebase bindings."""

from unittest.mock import patch

from sase.ace.changespec import ChangeSpec, CommentEntry
from sase.ace.tui.widgets import KeybindingFooter


def _make_changespec(
    name: str = "test_feature",
    description: str = "Test description",
    status: str = "Ready",
    cl: str | None = None,
    parent: str | None = None,
    file_path: str = "/tmp/test.gp",
    comments: list[CommentEntry] | None = None,
) -> ChangeSpec:
    """Create a mock ChangeSpec for testing."""
    return ChangeSpec(
        name=name,
        description=description,
        parent=parent,
        cl=cl,
        status=status,
        test_targets=None,
        kickstart=None,
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
    # Create a changespec with a fix-hook comment to trigger workflow
    comment = CommentEntry(
        reviewer="fix-hook",
        file_path="test.py",
    )
    changespec = _make_changespec(status="Ready", comments=[comment])

    with patch(
        "sase.ace.tui.widgets._keybinding_bindings.get_available_workflows"
    ) as mock:
        mock.return_value = ["fix"]
        bindings = footer._compute_available_bindings(changespec)

    binding_dict = dict(bindings)
    assert "r" in binding_dict
    assert "fix" in binding_dict["r"]


def test_keybinding_footer_workflow_binding_multiple() -> None:
    """Test 'r' (run) binding shows count when multiple workflows available."""
    footer = KeybindingFooter()
    changespec = _make_changespec(status="Ready")

    with patch(
        "sase.ace.tui.widgets._keybinding_bindings.get_available_workflows"
    ) as mock:
        mock.return_value = ["fix", "crs"]
        bindings = footer._compute_available_bindings(changespec)

    binding_dict = dict(bindings)
    assert "r" in binding_dict
    assert "2 workflows" in binding_dict["r"]


# --- Edit, Copy, Fold Binding Tests ---
