"""Tests for CL updates, Draft suffix, parent-child constraints, and description updates."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.status_state_machine import transition_changespec_status
from sase.status_state_machine.field_updates import (
    apply_cl_update,
    apply_description_update,
)


def _create_test_project_file_with_suffix(
    name: str = "Test Feature", status: str = "Ready"
) -> str:
    """Create a temporary project file with a specific NAME for suffix testing."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".md") as f:
        f.write(f"""# Test Project

## ChangeSpec

NAME: {name}
DESCRIPTION:
  A test feature for unit testing
PARENT: None
CL: None
STATUS: {status}
TEST TARGETS: None

---
""")
        return f.name


def test_apply_cl_update_sets_cl() -> None:
    """Test apply_cl_update sets CL field."""
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  Test description\n",
        "CL: old_cl\n",
        "STATUS: Draft\n",
    ]
    result = apply_cl_update(lines, "Test Feature", "new_cl_value", "/nonexistent")
    assert "CL: new_cl_value\n" in result
    assert "CL: old_cl\n" not in result


def test_apply_cl_update_removes_cl() -> None:
    """Test apply_cl_update removes CL when None."""
    lines = [
        "NAME: Test Feature\n",
        "CL: old_cl\n",
        "STATUS: Draft\n",
    ]
    result = apply_cl_update(lines, "Test Feature", None, "/nonexistent")
    assert "CL:" not in result


def test_apply_cl_update_adds_cl_before_status() -> None:
    """Test apply_cl_update adds CL before STATUS when missing."""
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  Test description\n",
        "STATUS: Draft\n",
    ]
    with patch(
        "sase.status_state_machine.field_updates.get_change_label",
        return_value="CL",
    ):
        result = apply_cl_update(lines, "Test Feature", "new_cl", "/nonexistent")
    assert "CL: new_cl\n" in result
    # CL should appear before STATUS
    lines_list = result.split("\n")
    cl_idx = next(i for i, ln in enumerate(lines_list) if "CL:" in ln)
    status_idx = next(i for i, ln in enumerate(lines_list) if "STATUS:" in ln)
    assert cl_idx < status_idx


# === Draft children constraint tests ===


def test_transition_to_draft_blocked_when_child_is_ready() -> None:
    """Test that transition to Draft is blocked when a child has Ready status."""
    project_file = _create_test_project_file_with_suffix(
        name="Parent Feature", status="Ready"
    )

    try:
        # Mock find_all_changespecs to return a child with Ready status
        mock_child = MagicMock()
        mock_child.name = "Child Feature"
        mock_child.parent = "Parent Feature"
        mock_child.status = "Ready"

        with patch("sase.ace.changespec.find_all_changespecs") as mock_find:
            mock_find.return_value = [mock_child]

            success, old_status, error, _ = transition_changespec_status(
                project_file, "Parent Feature", "Draft", validate=True
            )

            assert success is False
            assert old_status == "Ready"
            assert error is not None
            assert "Cannot transition 'Parent Feature' to Draft" in error
            assert "children must be WIP, Draft, or Reverted" in error
            assert "Child Feature (Ready)" in error

    finally:
        Path(project_file).unlink()


def test_transition_to_draft_allowed_when_children_are_draft_or_reverted() -> None:
    """Test that transition to Draft succeeds when children are Draft or Reverted."""
    project_file = _create_test_project_file_with_suffix(
        name="Parent Feature", status="Ready"
    )

    try:
        # Mock find_all_changespecs to return children with valid statuses
        mock_child_draft = MagicMock()
        mock_child_draft.name = "Child Draft"
        mock_child_draft.parent = "Parent Feature"
        mock_child_draft.status = "Draft"

        mock_child_reverted = MagicMock()
        mock_child_reverted.name = "Child Reverted"
        mock_child_reverted.parent = "Parent Feature"
        mock_child_reverted.status = "Reverted"

        # Also include an unrelated child (different parent)
        mock_unrelated = MagicMock()
        mock_unrelated.name = "Unrelated"
        mock_unrelated.parent = "Other Parent"
        mock_unrelated.status = "Ready"

        with (
            patch("sase.ace.changespec.find_all_changespecs") as mock_find,
            patch("sase.ace.mentors.set_mentor_draft_flags"),
            patch("sase.ace.revert.update_changespec_name_atomic"),
            patch("sase.running_field.get_workspace_directory") as mock_ws_dir,
            patch("sase.running_field.update_running_field_cl_name"),
        ):
            mock_find.return_value = [
                mock_child_draft,
                mock_child_reverted,
                mock_unrelated,
            ]
            mock_ws_dir.side_effect = RuntimeError("No workspace")

            success, old_status, error, _ = transition_changespec_status(
                project_file, "Parent Feature", "Draft", validate=True
            )

            assert success is True
            assert old_status == "Ready"
            assert error is None

    finally:
        Path(project_file).unlink()


def test_transition_from_draft_blocked_when_parent_is_draft() -> None:
    """Test that child cannot transition away from Draft/Reverted when parent is Draft."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".md") as f:
        f.write("""# Test Project

## ChangeSpec

NAME: Parent Feature
DESCRIPTION:
  A parent feature
CL: None
STATUS: Draft
TEST TARGETS: None


## ChangeSpec

NAME: Child Feature
DESCRIPTION:
  A child feature
PARENT: Parent Feature
CL: None
STATUS: Draft
TEST TARGETS: None

---
""")
        project_file = f.name

    try:
        # Try to transition child from Draft to Ready when parent is Draft
        success, old_status, error, _ = transition_changespec_status(
            project_file, "Child Feature", "Ready", validate=True
        )

        assert success is False
        assert old_status == "Draft"
        assert error is not None
        assert "Cannot transition 'Child Feature' to Ready" in error
        assert "parent 'Parent Feature' is Draft" in error
        assert (
            "Children of WIP/Draft ChangeSpecs must be WIP, Draft, or Reverted" in error
        )

    finally:
        Path(project_file).unlink()


def test_transition_from_draft_allowed_when_parent_is_not_draft() -> None:
    """Test that child can transition when parent is not Draft."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".md") as f:
        f.write("""# Test Project

## ChangeSpec

NAME: Parent Feature
DESCRIPTION:
  A parent feature
CL: None
STATUS: Ready
TEST TARGETS: None


## ChangeSpec

NAME: Child Feature
DESCRIPTION:
  A child feature
PARENT: Parent Feature
CL: None
STATUS: Draft
TEST TARGETS: None

---
""")
        project_file = f.name

    try:
        # Mock the external dependencies
        with (
            patch("sase.ace.mentors.clear_mentor_draft_flags"),
            patch("sase.sase_utils.has_suffix") as mock_has_suffix,
        ):
            mock_has_suffix.return_value = False

            # Transition child from Draft to Ready when parent is Ready
            success, old_status, error, _ = transition_changespec_status(
                project_file, "Child Feature", "Ready", validate=True
            )

            assert success is True
            assert old_status == "Draft"
            assert error is None

    finally:
        Path(project_file).unlink()


def test_transition_to_reverted_allowed_when_parent_is_draft() -> None:
    """Test that child can transition to Reverted even when parent is Draft."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".md") as f:
        f.write("""# Test Project

## ChangeSpec

NAME: Parent Feature
DESCRIPTION:
  A parent feature
CL: None
STATUS: Draft
TEST TARGETS: None


## ChangeSpec

NAME: Child Feature
DESCRIPTION:
  A child feature
PARENT: Parent Feature
CL: None
STATUS: Draft
TEST TARGETS: None

---
""")
        project_file = f.name

    try:
        # Transition child to Reverted - this should succeed even with Draft parent
        # Note: validate=False because Reverted is typically set via revert operation
        success, old_status, error, _ = transition_changespec_status(
            project_file, "Child Feature", "Reverted", validate=False
        )

        assert success is True
        assert old_status == "Draft"
        assert error is None

    finally:
        Path(project_file).unlink()


# === DESCRIPTION update tests ===


def test_apply_description_update_multi_line() -> None:
    """Test apply_description_update replaces a multi-line description with blank lines."""
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  Old line one\n",
        "\n",
        "  Old line two\n",
        "PARENT: None\n",
        "STATUS: Draft\n",
    ]
    result = apply_description_update(
        lines, "Test Feature", "New line one\n\nNew line two"
    )
    assert "  New line one\n" in result
    assert "  New line two\n" in result
    assert "Old line one" not in result
    assert "Old line two" not in result
    assert "PARENT: None\n" in result
    assert "STATUS: Draft\n" in result
