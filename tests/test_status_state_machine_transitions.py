"""Tests for status_state_machine file-based transitions and atomic operations."""

import tempfile
from pathlib import Path

from sase.status_state_machine import (
    transition_changespec_status,
)


def _create_test_project_file(status: str = "Ready") -> str:
    """Create a temporary project file with a test ChangeSpec."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".md") as f:
        f.write(f"""# Test Project

## ChangeSpec

NAME: Test Feature
DESCRIPTION:
  A test feature for unit testing
PARENT: None
CL: None
STATUS: {status}
TEST TARGETS: None

---
""")
        return f.name


def test_transition_changespec_status_invalid_transition() -> None:
    """Test that invalid transition is rejected."""
    project_file = _create_test_project_file("Ready")

    try:
        success, old_status, error, _ = transition_changespec_status(
            project_file, "Test Feature", "Submitted", validate=True
        )

        assert success is False
        assert old_status == "Ready"
        assert error is not None
        assert "Invalid status transition" in error

        # Verify the file was NOT updated
        with open(project_file) as f:
            content = f.read()
            assert "STATUS: Ready" in content
            assert "STATUS: Submitted" not in content

    finally:
        Path(project_file).unlink()


def test_transition_changespec_status_skip_validation() -> None:
    """Test that validation can be skipped with validate=False."""
    project_file = _create_test_project_file("Ready")

    try:
        # This transition would normally be invalid
        success, old_status, error, _ = transition_changespec_status(
            project_file, "Test Feature", "Submitted", validate=False
        )

        assert success is True
        assert old_status == "Ready"
        assert error is None

        # Verify the file was updated
        with open(project_file) as f:
            content = f.read()
            assert "STATUS: Submitted" in content

    finally:
        Path(project_file).unlink()


def test_transition_changespec_status_nonexistent_changespec() -> None:
    """Test handling of nonexistent ChangeSpec."""
    project_file = _create_test_project_file("Ready")

    try:
        success, old_status, error, _ = transition_changespec_status(
            project_file, "Nonexistent Feature", "Mailed", validate=True
        )

        assert success is False
        assert old_status is None
        assert error is not None
        assert "not found" in error

    finally:
        Path(project_file).unlink()


def _create_project_file_with_multiple_changespecs(
    changespecs: list[tuple[str, str, str | None]],
) -> str:
    """Create a project file with multiple ChangeSpecs.

    Args:
        changespecs: List of (name, status, parent) tuples.

    Returns:
        Path to the created project file.
    """
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".md") as f:
        f.write("# Test Project\n\n")
        for name, status, parent in changespecs:
            parent_val = parent if parent else "None"
            f.write(f"""## ChangeSpec

NAME: {name}
DESCRIPTION:
  Test description
PARENT: {parent_val}
CL: None
STATUS: {status}
TEST TARGETS: None

---

""")
        return f.name


def test_draft_to_ready_blocked_when_sibling_has_children() -> None:
    """Test Draft->Ready blocked when sibling Draft ChangeSpec has unreverted children."""
    from unittest.mock import patch

    # Create project file with:
    # - foo_bar__1 (Draft) - the one we're transitioning
    # - foo_bar__2 (Draft) - sibling that has a child
    # - child_of_2 (Ready) - child of foo_bar__2
    project_file = _create_project_file_with_multiple_changespecs(
        [
            ("foo_bar__1", "Draft", None),
            ("foo_bar__2", "Draft", None),
            ("child_of_2", "Ready", "foo_bar__2"),
        ]
    )

    try:
        # Mock find_all_changespecs to return our test ChangeSpecs
        from sase.ace.changespec import ChangeSpec

        mock_changespecs = [
            ChangeSpec(
                name="foo_bar__1",
                description="Test",
                parent=None,
                cl=None,
                status="Draft",
                test_targets=None,
                kickstart=None,
                file_path=project_file,
                line_number=6,
            ),
            ChangeSpec(
                name="foo_bar__2",
                description="Test",
                parent=None,
                cl=None,
                status="Draft",
                test_targets=None,
                kickstart=None,
                file_path=project_file,
                line_number=18,
            ),
            ChangeSpec(
                name="child_of_2",
                description="Test",
                parent="foo_bar__2",
                cl=None,
                status="Ready",
                test_targets=None,
                kickstart=None,
                file_path=project_file,
                line_number=30,
            ),
        ]

        with patch(
            "sase.ace.changespec.find_all_changespecs",
            return_value=mock_changespecs,
        ):
            success, old_status, error, _ = transition_changespec_status(
                project_file, "foo_bar__1", "Ready", validate=True
            )

        assert success is False
        assert old_status == "Draft"
        assert error is not None
        assert (
            "sibling ChangeSpec 'foo_bar__2' (Draft) has unreverted children" in error
        )

    finally:
        Path(project_file).unlink()


def test_draft_to_ready_allowed_when_sibling_children_reverted() -> None:
    """Test Draft->Ready allowed when sibling's children are all Reverted."""
    from unittest.mock import patch

    # Create project file with:
    # - foo_bar__1 (Draft) - the one we're transitioning
    # - foo_bar__2 (Draft) - sibling
    # - child_of_2 (Reverted) - child of foo_bar__2 that is reverted
    project_file = _create_project_file_with_multiple_changespecs(
        [
            ("foo_bar__1", "Draft", None),
            ("foo_bar__2", "Draft", None),
            ("child_of_2", "Reverted", "foo_bar__2"),
        ]
    )

    try:
        from sase.ace.changespec import ChangeSpec

        mock_changespecs = [
            ChangeSpec(
                name="foo_bar__1",
                description="Test",
                parent=None,
                cl=None,
                status="Draft",
                test_targets=None,
                kickstart=None,
                file_path=project_file,
                line_number=6,
            ),
            ChangeSpec(
                name="foo_bar__2",
                description="Test",
                parent=None,
                cl=None,
                status="Draft",
                test_targets=None,
                kickstart=None,
                file_path=project_file,
                line_number=18,
            ),
            ChangeSpec(
                name="child_of_2",
                description="Test",
                parent="foo_bar__2",
                cl=None,
                status="Reverted",
                test_targets=None,
                kickstart=None,
                file_path=project_file,
                line_number=30,
            ),
        ]

        with patch(
            "sase.ace.changespec.find_all_changespecs",
            return_value=mock_changespecs,
        ):
            # Also need to mock the functions called after successful transition
            with patch("sase.ace.mentors.clear_mentor_draft_flags"):
                with patch(
                    "sase.status_state_machine.transitions._handle_suffix_strip",
                    return_value=[],
                ):
                    success, old_status, error, _ = transition_changespec_status(
                        project_file, "foo_bar__1", "Ready", validate=True
                    )

        assert success is True
        assert old_status == "Draft"
        assert error is None

    finally:
        Path(project_file).unlink()
