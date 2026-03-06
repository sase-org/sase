"""Tests for commit_utils.modifiers module."""

import tempfile
from pathlib import Path

from sase.commit_utils import (
    mark_proposal_broken,
    reject_proposals_and_set_status_atomic,
)


def _create_test_project_file(content: str) -> Path:
    """Create a temporary project file with the given content."""
    fd, path = tempfile.mkstemp(suffix=".gp")
    with open(path, "w") as f:
        f.write(content)
    return Path(path)


def test_reject_proposals_and_set_status_atomic_keeps_status() -> None:
    """Test empty final_status keeps current status while rejecting proposals."""
    content = """NAME: test-cl
STATUS: Ready
COMMITS:
  (1) First commit
  (2a) Proposal A - (!: NEW PROPOSAL)
"""
    project_file = _create_test_project_file(content)
    try:
        result = reject_proposals_and_set_status_atomic(
            str(project_file), "test-cl", ""
        )
        assert result is True

        # Read back and verify
        with open(project_file) as f:
            new_content = f.read()

        assert "STATUS: Ready\n" in new_content
        assert "(~!: NEW PROPOSAL)" in new_content
    finally:
        project_file.unlink()


def test_reject_proposals_and_set_status_atomic_wrong_cl() -> None:
    """Test when the CL name doesn't match."""
    content = """NAME: other-cl
STATUS: Ready
COMMITS:
  (1) First commit
"""
    project_file = _create_test_project_file(content)
    try:
        result = reject_proposals_and_set_status_atomic(
            str(project_file), "test-cl", "Mailed"
        )
        # Should fail because the CL name doesn't match
        assert result is False
    finally:
        project_file.unlink()


def test_reject_proposals_and_set_status_atomic_with_mentors_section() -> None:
    """Test that MENTORS section is handled correctly (stops in_commits)."""
    content = """NAME: test-cl
STATUS: Ready
COMMITS:
  (1) First commit
  (2a) Proposal A - (!: NEW PROPOSAL)
MENTORS:
  mentor1@example.com
"""
    project_file = _create_test_project_file(content)
    try:
        result = reject_proposals_and_set_status_atomic(
            str(project_file), "test-cl", "Mailed"
        )
        assert result is True

        with open(project_file) as f:
            new_content = f.read()

        assert "STATUS: Mailed" in new_content
        assert "(~!: NEW PROPOSAL)" in new_content
        assert "MENTORS:" in new_content
    finally:
        project_file.unlink()


def test_mark_proposal_broken_already_rejected() -> None:
    """Test when the entry is already rejected (not a NEW PROPOSAL)."""
    content = """NAME: test-cl
STATUS: Ready
COMMITS:
  (1) First commit
  (2a) Proposal A - (~!: NEW PROPOSAL)
"""
    project_file = _create_test_project_file(content)
    try:
        result = mark_proposal_broken(str(project_file), "test-cl", "2a")
        # Should fail because it's already rejected, not (!: NEW PROPOSAL)
        assert result is False
    finally:
        project_file.unlink()


def test_mark_proposal_broken_multiple_changespecs() -> None:
    """Test with multiple changespecs in the file."""
    content = """NAME: first-cl
STATUS: Ready
COMMITS:
  (1) First commit
  (2a) Proposal A - (!: NEW PROPOSAL)

NAME: test-cl
STATUS: Ready
COMMITS:
  (1) First commit
  (3a) Proposal B - (!: NEW PROPOSAL)

NAME: third-cl
STATUS: Ready
COMMITS:
  (1) Third commit
"""
    project_file = _create_test_project_file(content)
    try:
        result = mark_proposal_broken(str(project_file), "test-cl", "3a")
        assert result is True

        # Read back and verify
        with open(project_file) as f:
            new_content = f.read()

        # Only test-cl's 3a should be marked as broken
        assert "(3a) Proposal B - (~!: BROKEN PROPOSAL)" in new_content
        # first-cl's 2a should still be a new proposal
        assert "(2a) Proposal A - (!: NEW PROPOSAL)" in new_content
    finally:
        project_file.unlink()
