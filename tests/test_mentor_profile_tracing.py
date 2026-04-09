"""Tests for trace_profile_matching in the mentor_profile_matching module."""

from unittest.mock import patch

from sase.ace.changespec import CommitEntry
from sase.ace.scheduler.mentor_profile_matching import trace_profile_matching
from sase.config.mentor import MentorProfileConfig
from test_utils import build_changespec, make_mentor_config


def test_trace_profile_matching_first_commit_match() -> None:
    """Trace correctly reports first_commit match."""
    profile = MentorProfileConfig(
        profile_name="init_review",
        mentors=[make_mentor_config()],
        first_commit=True,
    )
    cs = build_changespec(
        commits=[CommitEntry(number=1, note="Initial commit")],
    )
    with patch(
        "sase.ace.scheduler.mentor_profile_matching.get_all_mentor_profiles",
        return_value=[profile],
    ):
        traces = trace_profile_matching(cs)

    assert len(traces) == 1
    assert traces[0].overall_match is True
    first_cr = next(
        cr for cr in traces[0].criteria_results if cr.criterion == "first_commit"
    )
    assert first_cr.configured is True
    assert first_cr.matched is True


def test_trace_profile_matching_no_match() -> None:
    """Trace correctly reports no match when criteria don't apply."""
    profile = MentorProfileConfig(
        profile_name="init_review",
        mentors=[make_mentor_config()],
        first_commit=True,
    )
    cs = build_changespec(
        commits=[CommitEntry(number=2, note="Second commit")],
    )
    with patch(
        "sase.ace.scheduler.mentor_profile_matching.get_all_mentor_profiles",
        return_value=[profile],
    ):
        traces = trace_profile_matching(cs)

    assert len(traces) == 1
    assert traces[0].overall_match is False


def test_trace_profile_matching_amend_note_match() -> None:
    """Trace correctly reports amend_note_regexes match."""
    profile = MentorProfileConfig(
        profile_name="note_matcher",
        mentors=[make_mentor_config()],
        amend_note_regexes=[r"fix.*bug"],
    )
    cs = build_changespec(
        commits=[CommitEntry(number=1, note="fix the bug in parser")],
    )
    with patch(
        "sase.ace.scheduler.mentor_profile_matching.get_all_mentor_profiles",
        return_value=[profile],
    ):
        traces = trace_profile_matching(cs)

    assert len(traces) == 1
    assert traces[0].overall_match is True
    note_cr = next(
        cr for cr in traces[0].criteria_results if cr.criterion == "amend_note_regexes"
    )
    assert note_cr.configured is True
    assert note_cr.matched is True
    assert "fix.*bug" in note_cr.details


def test_trace_profile_matching_empty_profiles() -> None:
    """Trace returns empty list when no profiles loaded."""
    cs = build_changespec(
        commits=[CommitEntry(number=1, note="commit")],
    )
    with patch(
        "sase.ace.scheduler.mentor_profile_matching.get_all_mentor_profiles",
        return_value=[],
    ):
        traces = trace_profile_matching(cs)

    assert traces == []


# Tests for project scoping in traces


def test_trace_profile_matching_projects_mismatch() -> None:
    """Trace correctly reports projects mismatch and short-circuits."""
    profile = MentorProfileConfig(
        profile_name="scoped",
        mentors=[make_mentor_config()],
        first_commit=True,
        projects=["sase"],
    )
    cs = build_changespec(
        file_path="/home/user/.sase/projects/bug/bug.gp",
        commits=[CommitEntry(number=1, note="commit")],
    )
    with patch(
        "sase.ace.scheduler.mentor_profile_matching.get_all_mentor_profiles",
        return_value=[profile],
    ):
        traces = trace_profile_matching(cs)

    assert len(traces) == 1
    assert traces[0].overall_match is False
    proj_cr = next(
        cr for cr in traces[0].criteria_results if cr.criterion == "projects"
    )
    assert proj_cr.configured is True
    assert proj_cr.matched is False
    assert "not in" in proj_cr.details


def test_trace_profile_matching_projects_match() -> None:
    """Trace correctly reports projects match and continues to other criteria."""
    profile = MentorProfileConfig(
        profile_name="scoped",
        mentors=[make_mentor_config()],
        first_commit=True,
        projects=["sase"],
    )
    cs = build_changespec(
        file_path="/home/user/.sase/projects/sase/sase.gp",
        commits=[CommitEntry(number=1, note="commit")],
    )
    with patch(
        "sase.ace.scheduler.mentor_profile_matching.get_all_mentor_profiles",
        return_value=[profile],
    ):
        traces = trace_profile_matching(cs)

    assert len(traces) == 1
    assert traces[0].overall_match is True
    proj_cr = next(
        cr for cr in traces[0].criteria_results if cr.criterion == "projects"
    )
    assert proj_cr.configured is True
    assert proj_cr.matched is True


def test_trace_profile_matching_reads_diff_once_per_invocation() -> None:
    """Trace reuses cached diff artifacts across multiple profiles."""
    profile_one = MentorProfileConfig(
        profile_name="one",
        mentors=[make_mentor_config()],
        diff_regexes=[r"token"],
    )
    profile_two = MentorProfileConfig(
        profile_name="two",
        mentors=[make_mentor_config()],
        diff_regexes=[r"token"],
    )
    read_paths: list[str | None] = []

    def _read_diff(diff_path: str | None) -> str | None:
        read_paths.append(diff_path)
        return "diff --git a/src/main.py b/src/main.py\n+token\n"

    cs = build_changespec(
        commits=[CommitEntry(number=1, note="n", diff="~/.sase/diffs/sample.diff")]
    )
    with (
        patch(
            "sase.ace.scheduler.mentor_profile_matching.get_all_mentor_profiles",
            return_value=[profile_one, profile_two],
        ),
        patch(
            "sase.ace.scheduler.mentor_profile_matching._read_diff_content",
            side_effect=_read_diff,
        ),
        patch(
            "sase.ace.scheduler.mentor_profile_matching.preload_vcs_fallback_diff",
            return_value=None,
        ),
    ):
        traces = trace_profile_matching(cs)

    assert len(traces) == 2
    assert read_paths == ["~/.sase/diffs/sample.diff"]


# Tests for WIP status being skipped entirely by mentor checks
