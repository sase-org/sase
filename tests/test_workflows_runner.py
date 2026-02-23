"""Tests for the workflows_runner module."""

import os
import tempfile

from sase.ace.changespec import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    HookEntry,
    HookStatusLine,
)
from sase.ace.scheduler.workflows_runner.completer import _find_fix_hook_proposal
from sase.ace.scheduler.workflows_runner.monitor import (
    WORKFLOW_COMPLETE_MARKER,
    check_workflow_completion,
    get_running_crs_workflows,
    get_running_fix_hook_workflows,
)
from sase.ace.scheduler.workflows_runner.starter import (
    _crs_workflow_eligible,
    _fix_hook_workflow_eligible,
    get_project_basename,
    get_workflow_output_path,
)


def _make_changespec(
    name: str = "test_cl",
    file_path: str = "/path/to/test.gp",
    hooks: list[HookEntry] | None = None,
    comments: list[CommentEntry] | None = None,
    commits: list[CommitEntry] | None = None,
) -> ChangeSpec:
    """Create a test ChangeSpec with minimal required fields."""
    return ChangeSpec(
        name=name,
        file_path=file_path,
        description="test description",
        cl=None,
        parent=None,
        hooks=hooks,
        commits=commits,
        status="Ready",
        test_targets=None,
        comments=comments,
        kickstart=None,
        line_number=1,
    )


def testget_workflow_output_path() -> None:
    """Test get_workflow_output_path creates valid paths."""
    result = get_workflow_output_path("test_name", "crs", "251227_123456")
    assert "test_name_crs-251227_123456.txt" in result
    assert result.startswith(os.path.expanduser("~/.sase/workflows"))


def test_crs_workflow_eligible_no_comments() -> None:
    """Test CRS not eligible when no comments."""
    cs = _make_changespec(comments=None)
    result = _crs_workflow_eligible(cs)
    assert len(result) == 0


def test_fix_hook_workflow_eligible_passed_not_eligible() -> None:
    """Test fix-hook not eligible when hook PASSED."""
    status_line = HookStatusLine(
        commit_entry_num="1",
        timestamp="251227123456",
        status="PASSED",
        duration="5s",
        suffix=None,
    )
    hook = HookEntry(command="make test", status_lines=[status_line])
    cs = _make_changespec(hooks=[hook])
    result = _fix_hook_workflow_eligible(cs)
    assert len(result) == 0


def test_fix_hook_workflow_eligible_no_hooks() -> None:
    """Test fix-hook not eligible when no hooks."""
    cs = _make_changespec(hooks=None)
    result = _fix_hook_workflow_eligible(cs)
    assert len(result) == 0


def testcheck_workflow_completion_file_not_exists() -> None:
    """Test completion check when file doesn't exist."""
    result = check_workflow_completion("/nonexistent/path.txt")
    assert result == (False, None, None)


def testcheck_workflow_completion_no_marker() -> None:
    """Test completion check when marker not present."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        f.write("Some output without completion marker")
        temp_path = f.name

    try:
        result = check_workflow_completion(temp_path)
        assert result == (False, None, None)
    finally:
        os.unlink(temp_path)


def testcheck_workflow_completion_with_marker_success() -> None:
    """Test completion check when marker present with success."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        f.write("Some output\n")
        f.write(f"{WORKFLOW_COMPLETE_MARKER}2a EXIT_CODE: 0")
        temp_path = f.name

    try:
        completed, proposal_id, exit_code = check_workflow_completion(temp_path)
        assert completed is True
        assert proposal_id == "2a"
        assert exit_code == 0
    finally:
        os.unlink(temp_path)


def testget_running_crs_workflows_with_timestamp_suffix() -> None:
    """Test detecting running CRS workflows by PID-based suffix."""
    comment = CommentEntry(
        reviewer="critique",
        file_path="~/.sase/comments/test.json",
        suffix="crs-12345-251227_123456",
    )
    cs = _make_changespec(comments=[comment])
    result = get_running_crs_workflows(cs)
    assert len(result) == 1
    assert result[0] == ("critique", "crs-12345-251227_123456")


def testget_running_crs_workflows_no_comments() -> None:
    """Test running CRS workflows when no comments."""
    cs = _make_changespec(comments=None)
    result = get_running_crs_workflows(cs)
    assert len(result) == 0


def testget_running_fix_hook_workflows_with_timestamp_suffix() -> None:
    """Test detecting running fix-hook workflows by PID-based suffix."""
    status_line = HookStatusLine(
        commit_entry_num="1",
        timestamp="251227_100000",
        status="FAILED",
        duration="5s",
        suffix="fix_hook-12345-251227_123456",
        suffix_type="running_agent",
    )
    hook = HookEntry(command="make test", status_lines=[status_line])
    cs = _make_changespec(hooks=[hook])
    result = get_running_fix_hook_workflows(cs)
    assert len(result) == 1
    assert result[0] == ("make test", "251227_123456", "1", None)


def testget_running_fix_hook_workflows_with_non_timestamp_suffix() -> None:
    """Test that non-timestamp suffixes are not considered running."""
    status_line = HookStatusLine(
        commit_entry_num="1",
        timestamp="251227100000",
        status="FAILED",
        duration="5s",
        suffix="2a",  # This is a proposal ID, not a timestamp
    )
    hook = HookEntry(command="make test", status_lines=[status_line])
    cs = _make_changespec(hooks=[hook])
    result = get_running_fix_hook_workflows(cs)
    assert len(result) == 0


def testget_running_fix_hook_workflows_no_hooks() -> None:
    """Test running fix-hook workflows when no hooks."""
    cs = _make_changespec(hooks=None)
    result = get_running_fix_hook_workflows(cs)
    assert len(result) == 0


def testcheck_workflow_completion_with_parsing_error() -> None:
    """Test completion check when exit code is not a number."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        f.write("Some output\n")
        # EXIT_CODE value is not a number - should trigger ValueError
        f.write(f"{WORKFLOW_COMPLETE_MARKER}None EXIT_CODE: notanumber")
        temp_path = f.name

    try:
        completed, proposal_id, exit_code = check_workflow_completion(temp_path)
        # Should still mark as completed but with error values
        assert completed is True
        assert proposal_id is None
        assert exit_code == 1
    finally:
        os.unlink(temp_path)


def test_crs_workflow_eligible_multiple_comments_mixed() -> None:
    """Test CRS returns only eligible comments when mixed."""
    comments = [
        CommentEntry(
            reviewer="critique",
            file_path="~/.sase/comments/test1.json",
            suffix=None,  # Eligible
        ),
        CommentEntry(
            reviewer="other",
            file_path="~/.sase/comments/test3.json",
            suffix=None,  # Not eligible - wrong reviewer
        ),
    ]
    cs = _make_changespec(comments=comments)
    result = _crs_workflow_eligible(cs)
    assert len(result) == 1
    assert result[0].reviewer == "critique"


def testget_running_crs_workflows_other_reviewer_ignored() -> None:
    """Test that other reviewer types are not considered running."""
    comment = CommentEntry(
        reviewer="other",
        file_path="~/.sase/comments/test.json",
        suffix="251227123456",  # Has timestamp but wrong reviewer
    )
    cs = _make_changespec(comments=[comment])
    result = get_running_crs_workflows(cs)
    assert len(result) == 0


def testget_running_fix_hook_workflows_no_status_line() -> None:
    """Test running fix-hook workflows when hook has no status lines."""
    hook = HookEntry(command="make test", status_lines=[])
    cs = _make_changespec(hooks=[hook])
    result = get_running_fix_hook_workflows(cs)
    assert len(result) == 0


def testget_project_basename_complex_path() -> None:
    """Test extracting project basename from complex path."""
    cs = _make_changespec(file_path="/home/user/.sase/projects/my-project.gp")
    assert get_project_basename(cs) == "my-project"


# --- Tests for _find_fix_hook_proposal ---


def test_find_fix_hook_proposal_returns_display_number() -> None:
    """Test that proposal display_number is returned when matching fix-hook proposal exists."""
    commits = [
        CommitEntry(number=1, note="Initial commit"),
        CommitEntry(
            number=1,
            note="[fix-hook (1) make test] Fix the import",
            proposal_letter="a",
        ),
    ]
    cs = _make_changespec(commits=commits)
    result = _find_fix_hook_proposal(cs, "1")
    assert result == "1a"


def test_find_fix_hook_proposal_returns_none_when_note_wrong_prefix() -> None:
    """Test that None is returned when proposal note doesn't start with [fix-hook."""
    commits = [
        CommitEntry(number=1, note="Initial commit"),
        CommitEntry(number=1, note="Manual fix for test", proposal_letter="a"),
    ]
    cs = _make_changespec(commits=commits)
    result = _find_fix_hook_proposal(cs, "1")
    assert result is None
