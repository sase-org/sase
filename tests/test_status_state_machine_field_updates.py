"""Tests for CL updates, Draft suffix, parent-child constraints, and description updates."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.status_state_machine import transition_changespec_status
from sase.status_state_machine.field_updates import (
    _apply_cl_update,
    _apply_description_update,
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


def test__apply_cl_update_sets_cl() -> None:
    """Test _apply_cl_update sets CL field."""
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  Test description\n",
        "CL: old_cl\n",
        "STATUS: Draft\n",
    ]
    result = _apply_cl_update(lines, "Test Feature", "new_cl_value", "/nonexistent")
    assert "CL: new_cl_value\n" in result
    assert "CL: old_cl\n" not in result


def test__apply_cl_update_removes_cl() -> None:
    """Test _apply_cl_update removes CL when None."""
    lines = [
        "NAME: Test Feature\n",
        "CL: old_cl\n",
        "STATUS: Draft\n",
    ]
    result = _apply_cl_update(lines, "Test Feature", None, "/nonexistent")
    assert "CL:" not in result


def test__apply_cl_update_adds_cl_before_status() -> None:
    """Test _apply_cl_update adds CL before STATUS when missing."""
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  Test description\n",
        "STATUS: Draft\n",
    ]
    result = _apply_cl_update(lines, "Test Feature", "new_cl", "/nonexistent")
    assert "CL: new_cl\n" in result
    # CL should appear before STATUS
    lines_list = result.split("\n")
    cl_idx = next(i for i, ln in enumerate(lines_list) if "CL:" in ln)
    status_idx = next(i for i, ln in enumerate(lines_list) if "STATUS:" in ln)
    assert cl_idx < status_idx


def test_transition_changespec_status_ready_to_draft_adds_suffix() -> None:
    """Test that Ready -> Draft transition adds __<N> suffix."""
    project_file = _create_test_project_file_with_suffix(
        name="Test Feature", status="Ready"
    )

    try:
        # Mock functions imported at runtime - use source module paths
        with (
            patch("sase.ace.changespec.find_all_changespecs") as mock_find,
            patch("sase.ace.mentors.set_mentor_draft_flags") as mock_set_draft,
            patch("sase.ace.revert.update_changespec_name_atomic") as mock_rename,
            patch("sase.running_field.get_workspace_directory") as mock_ws_dir,
            patch(
                "sase.status_state_machine.field_updates.update_parent_references_atomic"
            ) as mock_parent_refs,
            patch("sase.running_field.update_running_field_cl_name"),
        ):
            mock_find.return_value = []
            mock_ws_dir.side_effect = RuntimeError("No workspace")

            success, old_status, error, _ = transition_changespec_status(
                project_file, "Test Feature", "Draft", validate=True
            )

            assert success is True
            assert old_status == "Ready"
            assert error is None

            # Verify NAME rename was called with correct suffix
            mock_rename.assert_called_once_with(
                project_file, "Test Feature", "Test Feature__1"
            )

            # Verify PARENT references were updated
            mock_parent_refs.assert_called_once_with(
                project_file, "Test Feature", "Test Feature__1"
            )

            # Verify set_mentor_draft_flags was called
            mock_set_draft.assert_called_once()

    finally:
        Path(project_file).unlink()


def test_transition_changespec_status_ready_to_draft_increments_suffix() -> None:
    """Test that Ready -> Draft uses next available suffix number."""
    project_file = _create_test_project_file_with_suffix(
        name="Test Feature", status="Ready"
    )

    try:
        # Mock find_all_changespecs to return existing suffixed names
        mock_cs1 = MagicMock()
        mock_cs1.name = "Test Feature__1"
        mock_cs2 = MagicMock()
        mock_cs2.name = "Test Feature__2"

        # Mock functions imported at runtime - use source module paths
        with (
            patch("sase.ace.changespec.find_all_changespecs") as mock_find,
            patch("sase.ace.mentors.set_mentor_draft_flags"),
            patch("sase.ace.revert.update_changespec_name_atomic") as mock_rename,
            patch("sase.running_field.get_workspace_directory") as mock_ws_dir,
            patch(
                "sase.status_state_machine.field_updates.update_parent_references_atomic"
            ),
            patch("sase.running_field.update_running_field_cl_name"),
        ):
            mock_find.return_value = [mock_cs1, mock_cs2]
            mock_ws_dir.side_effect = RuntimeError("No workspace")

            success, old_status, error, _ = transition_changespec_status(
                project_file, "Test Feature", "Draft", validate=True
            )

            assert success is True

            # Should use __3 since __1 and __2 exist
            mock_rename.assert_called_once_with(
                project_file, "Test Feature", "Test Feature__3"
            )

    finally:
        Path(project_file).unlink()


def test_transition_changespec_status_ready_to_draft_updates_parent_refs() -> None:
    """Test that Ready -> Draft updates PARENT references in child ChangeSpecs."""
    # Create a project file with parent-child relationship
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
        # Mock functions imported at runtime - use source module paths
        with (
            patch("sase.ace.changespec.find_all_changespecs") as mock_find,
            patch("sase.ace.mentors.set_mentor_draft_flags"),
            patch("sase.ace.revert.update_changespec_name_atomic"),
            patch("sase.running_field.get_workspace_directory") as mock_ws_dir,
            patch(
                "sase.status_state_machine.field_updates.update_parent_references_atomic"
            ) as mock_parent_refs,
            patch("sase.running_field.update_running_field_cl_name"),
        ):
            mock_find.return_value = []
            mock_ws_dir.side_effect = RuntimeError("No workspace")

            success, _, _, _ = transition_changespec_status(
                project_file, "Parent Feature", "Draft", validate=True
            )

            assert success is True

            # Verify PARENT references update was called with old->new names
            mock_parent_refs.assert_called_once_with(
                project_file, "Parent Feature", "Parent Feature__1"
            )

    finally:
        Path(project_file).unlink()


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
            patch(
                "sase.status_state_machine.field_updates.update_parent_references_atomic"
            ),
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


def test__apply_description_update_single_line() -> None:
    """Test _apply_description_update replaces a single-line description."""
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  Old description\n",
        "PARENT: None\n",
        "CL: 12345\n",
        "STATUS: Draft\n",
    ]
    result = _apply_description_update(lines, "Test Feature", "New description")
    assert "DESCRIPTION:\n" in result
    assert "  New description\n" in result
    assert "Old description" not in result
    # Surrounding fields preserved
    assert "PARENT: None\n" in result
    assert "CL: 12345\n" in result
    assert "STATUS: Draft\n" in result


def test__apply_description_update_multi_line() -> None:
    """Test _apply_description_update replaces a multi-line description with blank lines."""
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  Old line one\n",
        "\n",
        "  Old line two\n",
        "PARENT: None\n",
        "STATUS: Draft\n",
    ]
    result = _apply_description_update(
        lines, "Test Feature", "New line one\n\nNew line two"
    )
    assert "  New line one\n" in result
    assert "  New line two\n" in result
    assert "Old line one" not in result
    assert "Old line two" not in result
    assert "PARENT: None\n" in result
    assert "STATUS: Draft\n" in result


def test__apply_description_update_only_targets_correct_changespec() -> None:
    """Test _apply_description_update only modifies the target ChangeSpec."""
    lines = [
        "NAME: First Feature\n",
        "DESCRIPTION:\n",
        "  First description\n",
        "STATUS: Draft\n",
        "\n",
        "NAME: Second Feature\n",
        "DESCRIPTION:\n",
        "  Second description\n",
        "STATUS: Ready\n",
    ]
    result = _apply_description_update(lines, "Second Feature", "Updated second")
    # First feature's description should be untouched
    assert "  First description\n" in result
    # Second feature's description should be updated
    assert "  Updated second\n" in result
    assert "  Second description" not in result


def test__apply_description_update_preserves_surrounding_fields() -> None:
    """Test that surrounding fields (PARENT, CL, STATUS) are preserved."""
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  Old description line 1\n",
        "  Old description line 2\n",
        "PARENT: Parent CL\n",
        "CL: 99999\n",
        "STATUS: Ready\n",
        "TEST TARGETS: //foo:bar_test\n",
    ]
    result = _apply_description_update(lines, "Test Feature", "Brand new desc")
    result_lines = result.splitlines(keepends=True)
    # Verify all surrounding fields are present and in order
    field_order = []
    for line in result_lines:
        if line.startswith("NAME:"):
            field_order.append("NAME")
        elif line.startswith("DESCRIPTION:"):
            field_order.append("DESCRIPTION")
        elif line.startswith("PARENT:"):
            field_order.append("PARENT")
        elif line.startswith("CL:"):
            field_order.append("CL")
        elif line.startswith("STATUS:"):
            field_order.append("STATUS")
        elif line.startswith("TEST TARGETS:"):
            field_order.append("TEST TARGETS")
    assert field_order == [
        "NAME",
        "DESCRIPTION",
        "PARENT",
        "CL",
        "STATUS",
        "TEST TARGETS",
    ]
