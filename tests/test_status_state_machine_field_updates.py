"""Tests for PR updates, Draft suffix, parent-child constraints, and description updates."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.status_state_machine import (
    transition_patch_status,
    update_patch_pr_origin_atomic,
)
from sase.status_state_machine.field_updates import (
    _apply_bug_update,
    _apply_pr_origin_update,
    _apply_pr_url_update,
    _apply_description_update,
)


def _create_test_project_file_with_suffix(
    tmp_path: Path,
    name: str = "Test Feature",
    status: str = "Ready",
) -> str:
    """Create a temporary project file with a specific NAME for suffix testing."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", delete=False, suffix=".md"
    ) as f:
        f.write(f"""# Test Project

## ChangeSpec

NAME: {name}
DESCRIPTION:
  A test feature for unit testing
PARENT: None
PR: None
STATUS: {status}

---
""")
        return f.name


def test__apply_pr_url_update_sets_pr_url() -> None:
    """Test _apply_pr_url_update sets PR URL field."""
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  Test description\n",
        "CL: old_pr\n",
        "STATUS: Draft\n",
    ]
    result = _apply_pr_url_update(lines, "Test Feature", "new_pr_value", "/nonexistent")
    assert "PR: new_pr_value\n" in result
    assert "CL: old_pr\n" not in result


def test__apply_pr_url_update_removes_cl() -> None:
    """Test _apply_pr_url_update removes PR/legacy PR when None."""
    lines = [
        "NAME: Test Feature\n",
        "CL: old_cl\n",
        "STATUS: Draft\n",
    ]
    result = _apply_pr_url_update(lines, "Test Feature", None, "/nonexistent")
    assert "CL:" not in result
    assert "PR:" not in result


def test__apply_pr_url_update_adds_pr_before_status() -> None:
    """Test _apply_pr_url_update adds PR before STATUS when missing."""
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  Test description\n",
        "STATUS: Draft\n",
    ]
    result = _apply_pr_url_update(lines, "Test Feature", "new_pr", "/nonexistent")
    assert "PR: new_pr\n" in result
    # PR should appear before STATUS
    lines_list = result.split("\n")
    cl_idx = next(i for i, ln in enumerate(lines_list) if "PR:" in ln)
    status_idx = next(i for i, ln in enumerate(lines_list) if "STATUS:" in ln)
    assert cl_idx < status_idx


# === Draft children constraint tests ===


def test_transition_to_draft_blocked_when_child_is_ready(tmp_path: Path) -> None:
    """Test that transition to Draft is blocked when a child has Ready status."""
    project_file = _create_test_project_file_with_suffix(
        tmp_path, name="Parent Feature", status="Ready"
    )

    try:
        # Mock find_all_patches to return a child with Ready status
        mock_child = MagicMock()
        mock_child.name = "Child Feature"
        mock_child.parent = "Parent Feature"
        mock_child.status = "Ready"

        with patch("sase.ace.patch.find_all_patches") as mock_find:
            mock_find.return_value = [mock_child]

            success, old_status, error, _ = transition_patch_status(
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


def test_transition_to_draft_allowed_when_children_are_draft_or_reverted(
    tmp_path: Path,
) -> None:
    """Test that transition to Draft succeeds when children are Draft or Reverted."""
    project_file = _create_test_project_file_with_suffix(
        tmp_path, name="Parent Feature", status="Ready"
    )

    try:
        # Mock find_all_patches to return children with valid statuses
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
            patch("sase.ace.patch.find_all_patches") as mock_find,
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

            success, old_status, error, _ = transition_patch_status(
                project_file, "Parent Feature", "Draft", validate=True
            )

            assert success is True
            assert old_status == "Ready"
            assert error is None

    finally:
        Path(project_file).unlink()


def test_transition_from_draft_blocked_when_parent_is_draft(tmp_path: Path) -> None:
    """Test that child cannot transition away from Draft/Reverted when parent is Draft."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", delete=False, suffix=".md"
    ) as f:
        f.write("""# Test Project

## ChangeSpec

NAME: Parent Feature
DESCRIPTION:
  A parent feature
CL: None
STATUS: Draft


## ChangeSpec

NAME: Child Feature
DESCRIPTION:
  A child feature
PARENT: Parent Feature
CL: None
STATUS: Draft

---
""")
        project_file = f.name

    try:
        # Try to transition child from Draft to Ready when parent is Draft
        success, old_status, error, _ = transition_patch_status(
            project_file, "Child Feature", "Ready", validate=True
        )

        assert success is False
        assert old_status == "Draft"
        assert error is not None
        assert "Cannot transition 'Child Feature' to Ready" in error
        # The Phase 4B planner normalizes this error to omit the parent NAME
        # (only the parent's status is on the wire). The previous handler
        # included the parent name; this is the deliberate Phase 4 contract.
        assert "parent is Draft" in error
        assert "Children of WIP/Draft Patches must be WIP, Draft, or Reverted" in error

    finally:
        Path(project_file).unlink()


def test_transition_from_draft_allowed_when_parent_is_not_draft(tmp_path: Path) -> None:
    """Test that child can transition when parent is not Draft."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", delete=False, suffix=".md"
    ) as f:
        f.write("""# Test Project

## ChangeSpec

NAME: Parent Feature
DESCRIPTION:
  A parent feature
CL: None
STATUS: Ready


## ChangeSpec

NAME: Child Feature
DESCRIPTION:
  A child feature
PARENT: Parent Feature
CL: None
STATUS: Draft

---
""")
        project_file = f.name

    try:
        # Mock the external dependencies
        with (
            patch("sase.ace.mentors.clear_mentor_draft_flags"),
            patch("sase.core.status_wire_conversion.has_suffix") as mock_has_suffix,
        ):
            mock_has_suffix.return_value = False

            # Transition child from Draft to Ready when parent is Ready
            success, old_status, error, _ = transition_patch_status(
                project_file, "Child Feature", "Ready", validate=True
            )

            assert success is True
            assert old_status == "Draft"
            assert error is None

    finally:
        Path(project_file).unlink()


def test_transition_to_reverted_allowed_when_parent_is_draft(tmp_path: Path) -> None:
    """Test that child can transition to Reverted even when parent is Draft."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", delete=False, suffix=".md"
    ) as f:
        f.write("""# Test Project

## ChangeSpec

NAME: Parent Feature
DESCRIPTION:
  A parent feature
CL: None
STATUS: Draft


## ChangeSpec

NAME: Child Feature
DESCRIPTION:
  A child feature
PARENT: Parent Feature
CL: None
STATUS: Draft

---
""")
        project_file = f.name

    try:
        # Transition child to Reverted - this should succeed even with Draft parent
        # Note: validate=False because Reverted is typically set via revert operation
        success, old_status, error, _ = transition_patch_status(
            project_file, "Child Feature", "Reverted", validate=False
        )

        assert success is True
        assert old_status == "Draft"
        assert error is None

    finally:
        Path(project_file).unlink()


# === DESCRIPTION update tests ===


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


def test__apply_description_update_preserves_timestamps_after_description() -> None:
    """Regression: _apply_description_update must not discard TIMESTAMPS after DESCRIPTION."""
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  Old description\n",
        "TIMESTAMPS:\n",
        "  commit 240601_120000\n",
        "  status 240601_130000\n",
        "STATUS: Draft\n",
    ]
    result = _apply_description_update(lines, "Test Feature", "New description")
    assert "  New description\n" in result
    assert "Old description" not in result
    # TIMESTAMPS section must be fully preserved
    assert "TIMESTAMPS:\n" in result
    assert "  commit 240601_120000\n" in result
    assert "  status 240601_130000\n" in result
    assert "STATUS: Draft\n" in result


def test__apply_description_update_preserves_refs_and_deltas_boundaries() -> None:
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  Old description\n",
        "REFS:\n",
        "  research:202607/report.md\n",
        "DELTAS:\n",
        "  ~ src/example.py\n",
        "STATUS: Draft\n",
    ]

    result = _apply_description_update(lines, "Test Feature", "New description")

    assert "REFS:\n  research:202607/report.md\n" in result
    assert "DELTAS:\n  ~ src/example.py\n" in result


# === BUG field update tests ===


def test__apply_bug_update_replaces_existing() -> None:
    """Test _apply_bug_update replaces an existing BUG field."""
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  Test description\n",
        "BUG: old_bug\n",
        "STATUS: Draft\n",
    ]
    result = _apply_bug_update(lines, "Test Feature", "b/12345")
    assert "BUG: b/12345\n" in result
    assert "BUG: old_bug\n" not in result


def test__apply_bug_update_inserts_before_status() -> None:
    """Test _apply_bug_update inserts BUG before STATUS when absent."""
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  Test description\n",
        "CL: 123\n",
        "STATUS: Draft\n",
    ]
    result = _apply_bug_update(lines, "Test Feature", "b/99999")
    assert "BUG: b/99999\n" in result
    # BUG should appear before STATUS
    result_lines = result.split("\n")
    bug_idx = next(i for i, ln in enumerate(result_lines) if "BUG:" in ln)
    status_idx = next(i for i, ln in enumerate(result_lines) if "STATUS:" in ln)
    assert bug_idx < status_idx


def test__apply_bug_update_removes_bug() -> None:
    """Test _apply_bug_update removes BUG when new_bug is None."""
    lines = [
        "NAME: Test Feature\n",
        "BUG: old_bug\n",
        "STATUS: Draft\n",
    ]
    result = _apply_bug_update(lines, "Test Feature", None)
    assert "BUG:" not in result


def test__apply_bug_update_noop_when_patch_not_found() -> None:
    """Test _apply_bug_update is a no-op when target Patch is not found."""
    lines = [
        "NAME: Other Feature\n",
        "STATUS: Draft\n",
    ]
    result = _apply_bug_update(lines, "Test Feature", "b/12345")
    assert result == "".join(lines)


def test__apply_pr_origin_update_replaces_existing() -> None:
    """_apply_pr_origin_update replaces an existing PR_ORIGIN field."""
    lines = [
        "NAME: Test Feature\n",
        "PR: https://example.test/pull/1\n",
        "PR_ORIGIN: unknown\n",
        "STATUS: Draft\n",
    ]
    result = _apply_pr_origin_update(lines, "Test Feature", "external")
    assert "PR_ORIGIN: external\n" in result
    assert "PR_ORIGIN: unknown\n" not in result


def test__apply_pr_origin_update_inserts_before_bug() -> None:
    """PR_ORIGIN is inserted before BUG when both are absent and BUG exists."""
    lines = [
        "NAME: Test Feature\n",
        "PR: https://example.test/pull/1\n",
        "BUG: http://b/123\n",
        "STATUS: Draft\n",
    ]
    result = _apply_pr_origin_update(lines, "Test Feature", "sase")
    result_lines = result.split("\n")
    origin_idx = next(i for i, ln in enumerate(result_lines) if "PR_ORIGIN:" in ln)
    bug_idx = next(i for i, ln in enumerate(result_lines) if "BUG:" in ln)
    assert origin_idx < bug_idx


def test__apply_pr_origin_update_inserts_before_status_when_no_bug() -> None:
    """PR_ORIGIN is inserted before STATUS when there is no BUG field."""
    lines = [
        "NAME: Test Feature\n",
        "PR: https://example.test/pull/1\n",
        "STATUS: Draft\n",
    ]
    result = _apply_pr_origin_update(lines, "Test Feature", "external")
    result_lines = result.split("\n")
    origin_idx = next(i for i, ln in enumerate(result_lines) if "PR_ORIGIN:" in ln)
    status_idx = next(i for i, ln in enumerate(result_lines) if "STATUS:" in ln)
    assert origin_idx < status_idx


def test__apply_pr_origin_update_noop_when_patch_not_found() -> None:
    """_apply_pr_origin_update is a no-op when target Patch is not found."""
    lines = [
        "NAME: Other Feature\n",
        "STATUS: Draft\n",
    ]
    result = _apply_pr_origin_update(lines, "Test Feature", "external")
    assert result == "".join(lines)


def test_update_patch_pr_origin_atomic_round_trip(tmp_path: Path) -> None:
    """update_patch_pr_origin_atomic normalizes and persists PR_ORIGIN."""
    project_file = _create_test_project_file_with_suffix(tmp_path)

    update_patch_pr_origin_atomic(project_file, "Test Feature", "EXTERNAL")

    content = Path(project_file).read_text(encoding="utf-8")
    assert "PR_ORIGIN: external\n" in content
