"""Tests for ace/changespec/validation.py - ChangeSpec validation functions."""

from sase.ace.changespec.models import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
)
from sase.ace.changespec.validation import (
    all_hooks_passed_for_entries,
    get_current_and_proposal_entry_ids,
    has_any_error_suffix,
    has_any_running_agent,
    has_any_running_process,
    has_any_status_suffix,
    is_parent_ready_for_mail,
)


def _make_cs(**kwargs: object) -> ChangeSpec:
    """Helper to build a minimal ChangeSpec with overrides."""
    defaults: dict[str, object] = {
        "name": "test",
        "description": "desc",
        "parent": None,
        "cl": None,
        "status": "Draft",
        "test_targets": None,
        "kickstart": None,
        "file_path": "/tmp/test.gp",
        "line_number": 1,
    }
    defaults |= kwargs
    return ChangeSpec(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# has_any_status_suffix / has_any_error_suffix
# ---------------------------------------------------------------------------


def test_has_any_status_suffix_clean() -> None:
    cs = _make_cs()
    assert has_any_status_suffix(cs) is False
    assert has_any_error_suffix(cs) is False


def test_has_any_status_suffix_in_status_field() -> None:
    cs = _make_cs(status="Ready - (!: READY TO MAIL)")
    assert has_any_status_suffix(cs) is True
    assert has_any_error_suffix(cs) is True


def test_has_any_error_suffix_in_commits() -> None:
    entry = CommitEntry(number=1, note="fix", suffix="oops", suffix_type="error")
    cs = _make_cs(commits=[entry])
    assert has_any_error_suffix(cs) is True


def test_has_any_error_suffix_in_hooks() -> None:
    sl = HookStatusLine(
        commit_entry_num="1",
        timestamp="260101_120000",
        status="FAILED",
        suffix="Hook Command Failed",
        suffix_type="error",
    )
    hook = HookEntry(command="lint", status_lines=[sl])
    cs = _make_cs(hooks=[hook])
    assert has_any_error_suffix(cs) is True


def test_has_any_error_suffix_in_comments() -> None:
    comment = CommentEntry(
        reviewer="crs",
        file_path="/a.json",
        suffix="Unresolved Critique Comments",
        suffix_type="error",
    )
    cs = _make_cs(comments=[comment])
    assert has_any_error_suffix(cs) is True


def test_has_any_error_suffix_non_error_commit() -> None:
    entry = CommitEntry(
        number=1, note="fix", suffix="NEW PROPOSAL", suffix_type="plain"
    )
    cs = _make_cs(commits=[entry])
    assert has_any_error_suffix(cs) is False


def test_has_any_status_suffix_hooks_non_error() -> None:
    sl = HookStatusLine(
        commit_entry_num="1",
        timestamp="260101_120000",
        status="PASSED",
        suffix=None,
        suffix_type=None,
    )
    hook = HookEntry(command="lint", status_lines=[sl])
    cs = _make_cs(hooks=[hook])
    assert has_any_status_suffix(cs) is False


# ---------------------------------------------------------------------------
# is_parent_ready_for_mail
# ---------------------------------------------------------------------------


def test_parent_ready_no_parent() -> None:
    cs = _make_cs()
    assert is_parent_ready_for_mail(cs, []) is True


def test_parent_ready_submitted() -> None:
    parent = _make_cs(name="parent", status="Submitted")
    child = _make_cs(name="child", parent="parent")
    assert is_parent_ready_for_mail(child, [parent, child]) is True


def test_parent_ready_mailed() -> None:
    parent = _make_cs(name="parent", status="Mailed")
    child = _make_cs(name="child", parent="parent")
    assert is_parent_ready_for_mail(child, [parent, child]) is True


def test_parent_not_ready_draft() -> None:
    parent = _make_cs(name="parent", status="Draft")
    child = _make_cs(name="child", parent="parent")
    assert is_parent_ready_for_mail(child, [parent, child]) is False


def test_parent_not_found() -> None:
    child = _make_cs(name="child", parent="missing")
    assert is_parent_ready_for_mail(child, [child]) is True


# ---------------------------------------------------------------------------
# get_current_and_proposal_entry_ids
# ---------------------------------------------------------------------------


def test_get_entry_ids_no_commits() -> None:
    cs = _make_cs()
    assert get_current_and_proposal_entry_ids(cs) == []


def test_get_entry_ids_simple() -> None:
    commits = [
        CommitEntry(number=1, note="first"),
        CommitEntry(number=2, note="second"),
    ]
    cs = _make_cs(commits=commits)
    assert get_current_and_proposal_entry_ids(cs) == ["2"]


def test_get_entry_ids_with_proposals() -> None:
    commits = [
        CommitEntry(number=1, note="first"),
        CommitEntry(number=2, note="second"),
        CommitEntry(number=2, note="proposal a", proposal_letter="a"),
        CommitEntry(number=2, note="proposal b", proposal_letter="b"),
    ]
    cs = _make_cs(commits=commits)
    ids = get_current_and_proposal_entry_ids(cs)
    assert "2" in ids
    assert "2a" in ids
    assert "2b" in ids
    assert "1" not in ids


def test_get_entry_ids_all_proposals() -> None:
    commits = [
        CommitEntry(number=1, note="proposal only", proposal_letter="a"),
    ]
    cs = _make_cs(commits=commits)
    assert get_current_and_proposal_entry_ids(cs) == []


# ---------------------------------------------------------------------------
# all_hooks_passed_for_entries
# ---------------------------------------------------------------------------


def test_all_hooks_passed_no_hooks() -> None:
    cs = _make_cs()
    assert all_hooks_passed_for_entries(cs, ["1"]) is True


def test_all_hooks_passed_no_entry_ids() -> None:
    hook = HookEntry(command="lint")
    cs = _make_cs(hooks=[hook])
    assert all_hooks_passed_for_entries(cs, []) is True


def test_all_hooks_passed_true() -> None:
    sl = HookStatusLine(
        commit_entry_num="2",
        timestamp="260101_120000",
        status="PASSED",
    )
    hook = HookEntry(command="lint", status_lines=[sl])
    cs = _make_cs(hooks=[hook])
    assert all_hooks_passed_for_entries(cs, ["2"]) is True


def test_all_hooks_passed_failed() -> None:
    sl = HookStatusLine(
        commit_entry_num="2",
        timestamp="260101_120000",
        status="FAILED",
    )
    hook = HookEntry(command="lint", status_lines=[sl])
    cs = _make_cs(hooks=[hook])
    assert all_hooks_passed_for_entries(cs, ["2"]) is False


def test_all_hooks_passed_missing_entry() -> None:
    sl = HookStatusLine(
        commit_entry_num="1",
        timestamp="260101_120000",
        status="PASSED",
    )
    hook = HookEntry(command="lint", status_lines=[sl])
    cs = _make_cs(hooks=[hook])
    # Entry "2" has no status line
    assert all_hooks_passed_for_entries(cs, ["2"]) is False


def test_all_hooks_passed_skip_dollar_hooks() -> None:
    sl = HookStatusLine(
        commit_entry_num="1",
        timestamp="260101_120000",
        status="RUNNING",
    )
    hook = HookEntry(command="$presubmit", status_lines=[sl])
    cs = _make_cs(hooks=[hook])
    # Dollar-prefixed hooks are skipped
    assert all_hooks_passed_for_entries(cs, ["1"]) is True


# ---------------------------------------------------------------------------
# has_any_running_agent / has_any_running_process
# ---------------------------------------------------------------------------


def test_has_any_running_agent_hooks() -> None:
    sl = HookStatusLine(
        commit_entry_num="1",
        timestamp="260101_120000",
        status="RUNNING",
        suffix="fix-12345-260101_120000",
        suffix_type="running_agent",
    )
    hook = HookEntry(command="lint", status_lines=[sl])
    cs = _make_cs(hooks=[hook])
    assert has_any_running_agent(cs) is True


def test_has_any_running_agent_comments() -> None:
    comment = CommentEntry(
        reviewer="crs",
        file_path="/a.json",
        suffix="crs-99999-260101_120000",
        suffix_type="running_agent",
    )
    cs = _make_cs(comments=[comment])
    assert has_any_running_agent(cs) is True


def test_has_any_running_agent_mentors() -> None:
    msl = MentorStatusLine(
        profile_name="prof",
        mentor_name="mentor1",
        status="RUNNING",
        timestamp="260101_120000",
        suffix="mentor_prof-12345-260101_120000",
        suffix_type="running_agent",
    )
    mentor = MentorEntry(entry_id="1", profiles=["prof"], status_lines=[msl])
    cs = _make_cs(mentors=[mentor])
    assert has_any_running_agent(cs) is True


def test_has_any_running_agent_false() -> None:
    cs = _make_cs()
    assert has_any_running_agent(cs) is False


def test_has_any_running_process_true() -> None:
    sl = HookStatusLine(
        commit_entry_num="1",
        timestamp="260101_120000",
        status="RUNNING",
        suffix="12345",
        suffix_type="running_process",
    )
    hook = HookEntry(command="lint", status_lines=[sl])
    cs = _make_cs(hooks=[hook])
    assert has_any_running_process(cs) is True


def test_has_any_running_process_false() -> None:
    cs = _make_cs()
    assert has_any_running_process(cs) is False


def test_has_any_running_process_no_hooks() -> None:
    cs = _make_cs(hooks=None)
    assert has_any_running_process(cs) is False
