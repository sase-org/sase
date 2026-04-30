"""Tests for status_state_machine file-based transitions and atomic operations."""

import os
import tempfile
from pathlib import Path

from sase.status_state_machine import (
    transition_changespec_status,
)

_CHANGESPEC_TEMPLATE = """# Test Project

## ChangeSpec

NAME: Test Feature
DESCRIPTION:
  A test feature for unit testing
PARENT: None
CL: None
STATUS: {status}
TEST TARGETS: None

---
"""


def _create_test_project_file(status: str = "Ready", suffix: str = ".gp") -> str:
    """Create a temporary project file with a test ChangeSpec."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=suffix) as f:
        f.write(_CHANGESPEC_TEMPLATE.format(status=status))
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
    """Test that validation can be skipped and ChangeSpec moves to archive."""
    from sase.ace.changespec.archive import get_archive_file_path

    project_file = _create_test_project_file("Ready")
    archive_file = get_archive_file_path(project_file)

    try:
        # This transition (Ready→Submitted) would normally be invalid
        success, old_status, error, _ = transition_changespec_status(
            project_file, "Test Feature", "Submitted", validate=False
        )

        assert success is True
        assert old_status == "Ready"
        assert error is None

        # ChangeSpec should have been moved to the archive file
        assert os.path.isfile(archive_file)
        with open(archive_file) as f:
            assert "STATUS: Submitted" in f.read()

        # ChangeSpec should NOT be in the main file
        with open(project_file) as f:
            assert "NAME: Test Feature" not in f.read()

    finally:
        Path(project_file).unlink()
        if Path(archive_file).exists():
            Path(archive_file).unlink()


def test_mailed_to_submitted_records_status_timestamp_in_archive() -> None:
    """Mailed→Submitted records STATUS timestamp after moving to archive."""
    from sase.ace.changespec.archive import get_archive_file_path

    project_file = _create_test_project_file("Mailed")
    archive_file = get_archive_file_path(project_file)

    try:
        success, old_status, error, _ = transition_changespec_status(
            project_file, "Test Feature", "Submitted", validate=True
        )

        assert success is True
        assert old_status == "Mailed"
        assert error is None

        with open(archive_file) as f:
            archive_content = f.read()
        assert "NAME: Test Feature" in archive_content
        assert "STATUS: Submitted" in archive_content
        assert "TIMESTAMPS:" in archive_content
        assert "STATUS " in archive_content
        assert "Mailed -> Submitted" in archive_content

        with open(project_file) as f:
            main_content = f.read()
        assert "NAME: Test Feature" not in main_content

    finally:
        Path(project_file).unlink()
        if Path(archive_file).exists():
            Path(archive_file).unlink()


def test_submitted_to_wip_records_status_timestamp_in_main_file() -> None:
    """Submitted→WIP records STATUS timestamp after restoring from archive."""
    with tempfile.TemporaryDirectory() as tmpdir:
        main_file = os.path.join(tmpdir, "test.gp")
        archive_file = os.path.join(tmpdir, "test-archive.gp")

        with open(main_file, "w") as f:
            f.write("# Test Project\n")
        with open(archive_file, "w") as f:
            f.write(_CHANGESPEC_TEMPLATE.format(status="Submitted"))

        success, old_status, error, _ = transition_changespec_status(
            archive_file, "Test Feature", "WIP", validate=False
        )

        assert success is True
        assert old_status == "Submitted"
        assert error is None

        with open(main_file) as f:
            main_content = f.read()
        assert "NAME: Test Feature" in main_content
        assert "STATUS: WIP" in main_content
        assert "TIMESTAMPS:" in main_content
        assert "STATUS " in main_content
        assert "Submitted -> WIP" in main_content

        with open(archive_file) as f:
            archive_content = f.read()
        assert "NAME: Test Feature" not in archive_content


def test_transition_from_archive_to_main() -> None:
    """Test moving a ChangeSpec from archive back to main file (validate=False)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        main_file = os.path.join(tmpdir, "test.gp")
        archive_file = os.path.join(tmpdir, "test-archive.gp")

        # Set up: main file is empty, ChangeSpec is in the archive with Submitted status
        with open(main_file, "w") as f:
            f.write("# Test Project\n")
        with open(archive_file, "w") as f:
            f.write(_CHANGESPEC_TEMPLATE.format(status="Submitted"))

        # Transition from Submitted→WIP (via validate=False) on the archive file
        success, old_status, error, _ = transition_changespec_status(
            archive_file, "Test Feature", "WIP", validate=False
        )

        assert success is True
        assert old_status == "Submitted"
        assert error is None

        # ChangeSpec should have been moved to the main file
        with open(main_file) as f:
            assert "NAME: Test Feature" in f.read()

        # ChangeSpec should NOT be in the archive file
        with open(archive_file) as f:
            assert "NAME: Test Feature" not in f.read()


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
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".gp") as f:
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


def test_draft_to_ready_records_timestamp_with_base_name() -> None:
    """Draft→Ready transition records STATUS timestamp using the base name."""
    from unittest.mock import call, patch

    project_file = _create_project_file_with_multiple_changespecs(
        [("foo__1", "Draft", None)]
    )

    try:
        with (
            patch(
                "sase.ace.changespec.find_all_changespecs",
                return_value=[],
            ),
            patch("sase.ace.mentors.clear_mentor_draft_flags"),
            patch(
                "sase.status_state_machine.transitions.handle_suffix_strip",
                return_value=[],
            ),
            patch(
                "sase.ace.timestamps.recording.add_timestamp_entry_atomic",
                return_value=True,
            ) as mock_ts,
        ):
            success, old_status, _, _ = transition_changespec_status(
                project_file, "foo__1", "Ready", validate=True
            )

            assert success is True
            assert old_status == "Draft"

            # Verify timestamp was recorded with the base name, not the suffixed name
            mock_ts.assert_called_once()
            ts_call = mock_ts.call_args
            assert ts_call == call(project_file, "foo", "STATUS", "Draft -> Ready")

    finally:
        Path(project_file).unlink()


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
            # The Phase 4B planner normalizes this error to omit the sibling
            # status — only the sibling NAME stays on the wire. The previous
            # handler included "(Draft)"; this is the deliberate Phase 4
            # contract.
            "sibling ChangeSpec 'foo_bar__2' has unreverted children" in error
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
                    "sase.status_state_machine.transitions.handle_suffix_strip",
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
