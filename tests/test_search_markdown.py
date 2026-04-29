"""Tests for sase changespec search --format markdown output."""

from io import StringIO

from inline_snapshot import snapshot

from sase.ace.changespec import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
)
from sase.main.search_handler import _display_markdown, _md_status_indicator


def _cs(
    name: str = "test",
    description: str = "desc",
    status: str = "Ready",
    cl: str | None = None,
    parent: str | None = None,
    bug: str | None = None,
    kickstart: str | None = None,
    commits: list[CommitEntry] | None = None,
    hooks: list[HookEntry] | None = None,
    comments: list[CommentEntry] | None = None,
    mentors: list[MentorEntry] | None = None,
) -> ChangeSpec:
    return ChangeSpec(
        name=name,
        description=description,
        parent=parent,
        cl=cl,
        status=status,
        test_targets=None,
        kickstart=kickstart,
        file_path="/home/user/.sase/projects/myproject/myproject.gp",
        line_number=1,
        bug=bug,
        commits=commits,
        hooks=hooks,
        comments=comments,
        mentors=mentors,
    )


def _capture_markdown(changespecs: list[ChangeSpec], *, query: str = "") -> str:
    """Capture _display_markdown output as a string."""
    import sys

    old_stdout = sys.stdout
    sys.stdout = buf = StringIO()
    try:
        _display_markdown(changespecs, query=query)
    finally:
        sys.stdout = old_stdout
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Status indicator mapping
# ---------------------------------------------------------------------------


class TestMdStatusIndicator:
    def test_passed(self) -> None:
        assert _md_status_indicator("PASSED", None, None) == snapshot(
            ":white_check_mark: Passed"
        )

    def test_failed(self) -> None:
        assert _md_status_indicator("FAILED", None, None) == snapshot(":x: Failed")

    def test_running(self) -> None:
        assert _md_status_indicator("RUNNING", None, None) == snapshot(
            ":arrows_counterclockwise: Running"
        )

    def test_killed(self) -> None:
        assert _md_status_indicator("KILLED", None, None) == snapshot(":skull: Killed")

    def test_error_suffix_overrides_status(self) -> None:
        assert _md_status_indicator(
            "PASSED", "Hook Command Failed", "error"
        ) == snapshot(":x: Hook Command Failed")

    def test_running_agent_suffix(self) -> None:
        assert _md_status_indicator(
            "RUNNING", "fix_hook-123-260101_120000", "running_agent"
        ) == snapshot(":arrows_counterclockwise: fix_hook-123-260101_120000")

    def test_killed_agent_suffix(self) -> None:
        assert _md_status_indicator(
            "DEAD", "fix_hook-123-260101_120000", "killed_agent"
        ) == snapshot(":skull: fix_hook-123-260101_120000")

    def test_unknown_status_passthrough(self) -> None:
        assert _md_status_indicator("WEIRD", None, None) == snapshot("WEIRD")


# ---------------------------------------------------------------------------
# Minimal ChangeSpec
# ---------------------------------------------------------------------------


class TestMinimalChangeSpec:
    def test_minimal_output(self) -> None:
        out = _capture_markdown([_cs(name="my_feature", description="A simple fix")])
        assert out == snapshot("""\
# Search Results

Found 1 change(s): 1 Ready

## my_feature

**Status:** Ready · **Project:** myproject

> A simple fix

""")


# ---------------------------------------------------------------------------
# Full ChangeSpec with all sections
# ---------------------------------------------------------------------------


class TestFullChangeSpec:
    def test_full_output(self) -> None:
        cs = _cs(
            name="feature_auth",
            description="Add new feature for user authentication",
            status="Ready",
            parent="add_config_parser",
            bug="b/12345",
            cl="https://github.com/org/repo/pull/42",
            commits=[
                CommitEntry(number=1, note="Initial JWT validator"),
                CommitEntry(
                    number=2,
                    note="Alternative approach",
                    proposal_letter="a",
                    suffix="NEW PROPOSAL",
                ),
            ],
            hooks=[
                HookEntry(
                    command="run_tests",
                    status_lines=[
                        HookStatusLine(
                            commit_entry_num="1",
                            timestamp="260101_120000",
                            status="PASSED",
                            duration="1m23s",
                        ),
                        HookStatusLine(
                            commit_entry_num="2",
                            timestamp="260101_130000",
                            status="FAILED",
                            duration="2m15s",
                        ),
                    ],
                )
            ],
            comments=[
                CommentEntry(
                    reviewer="critique",
                    file_path="/home/user/.sase/comments/file.json",
                    suffix="Unresolved Critique Comments",
                    suffix_type="error",
                ),
                CommentEntry(
                    reviewer="review",
                    file_path="/home/user/.sase/comments/file2.json",
                ),
            ],
            mentors=[
                MentorEntry(
                    entry_id="1",
                    profiles=["perf_reviewer"],
                    status_lines=[
                        MentorStatusLine(
                            profile_name="perf_reviewer",
                            mentor_name="alice",
                            status="RUNNING",
                            timestamp="260101_140000",
                            suffix="mentor_alice-123-260101_140000",
                            suffix_type="running_agent",
                        ),
                        MentorStatusLine(
                            profile_name="code_reviewer",
                            mentor_name="bob",
                            status="PASSED",
                            timestamp="260101_150000",
                            duration="3h5m12s",
                        ),
                    ],
                )
            ],
        )
        out = _capture_markdown([cs])
        assert out == snapshot("""\
# Search Results

Found 1 change(s): 1 Ready

## feature_auth

**Status:** Ready · **Project:** myproject · **Parent:** add_config_parser · **Bug:** b/12345 **PR:** https://github.com/org/repo/pull/42

> Add new feature for user authentication

### Commits

| # | Description | Status |
| --- | --- | --- |
| 1 | Initial JWT validator |  |
| 2a | Alternative approach | :warning: Proposal |

### Test Hooks

| Hook | Commit | Result | Duration |
| --- | --- | --- | --- |
| run_tests | #1 | :white_check_mark: Passed | 1m23s |
| run_tests | #2 | :x: Failed | 2m15s |

### Review Comments

| Reviewer | Status |
| --- | --- |
| critique | :warning: Unresolved Critique Comments |
| review | :white_check_mark: |

### Mentors

| Commit | Mentor | Result | Duration |
| --- | --- | --- | --- |
| #1 | perf_reviewer / alice | :arrows_counterclockwise: mentor_alice-123-260101_140000 |  |
| #1 | code_reviewer / bob | :white_check_mark: Passed | 3h5m12s |

""")


# ---------------------------------------------------------------------------
# Multiple ChangeSpecs — separator
# ---------------------------------------------------------------------------


class TestMultipleChangeSpecs:
    def test_separator_between_changespecs(self) -> None:
        out = _capture_markdown(
            [
                _cs(name="first", status="WIP", description="First change"),
                _cs(name="second", status="Draft", description="Second change"),
            ]
        )
        assert out == snapshot("""\
# Search Results

Found 2 change(s): 1 Draft, 1 WIP

[first](#first) · [second](#second)

## first

**Status:** WIP · **Project:** myproject

> First change

---

## second

**Status:** Draft · **Project:** myproject

> Second change

""")


# ---------------------------------------------------------------------------
# Summary header accuracy
# ---------------------------------------------------------------------------


class TestSummaryHeader:
    def test_status_breakdown(self) -> None:
        out = _capture_markdown(
            [
                _cs(name="a", status="Ready"),
                _cs(name="b", status="Ready"),
                _cs(name="c", status="WIP"),
            ]
        )
        # First two lines: header + blank + summary
        lines = out.split("\n")
        assert lines[0] == "# Search Results"
        assert lines[2] == "Found 3 change(s): 2 Ready, 1 WIP"


# ---------------------------------------------------------------------------
# Null / empty field handling
# ---------------------------------------------------------------------------


class TestNullFields:
    def test_no_parent_no_cl_no_bug(self) -> None:
        out = _capture_markdown([_cs(name="bare")])
        assert "**Parent:**" not in out
        assert "**PR:**" not in out
        assert "**Bug:**" not in out

    def test_no_commits_section(self) -> None:
        out = _capture_markdown([_cs(name="bare")])
        assert "### Commits" not in out

    def test_no_hooks_section(self) -> None:
        out = _capture_markdown([_cs(name="bare")])
        assert "### Test Hooks" not in out

    def test_no_comments_section(self) -> None:
        out = _capture_markdown([_cs(name="bare")])
        assert "### Review Comments" not in out

    def test_no_mentors_section(self) -> None:
        out = _capture_markdown([_cs(name="bare")])
        assert "### Mentors" not in out


# ---------------------------------------------------------------------------
# Multi-line description
# ---------------------------------------------------------------------------


class TestMultiLineDescription:
    def test_preserves_paragraph_breaks(self) -> None:
        out = _capture_markdown(
            [
                _cs(
                    name="multi",
                    description="First paragraph\n\nSecond paragraph\nstill second",
                )
            ]
        )
        assert "> First paragraph" in out
        assert ">" in out  # blank blockquote line for paragraph break
        assert "> Second paragraph" in out
        assert "> still second" in out


# ---------------------------------------------------------------------------
# Query string in header
# ---------------------------------------------------------------------------


class TestQueryHeader:
    def test_query_in_header(self) -> None:
        out = _capture_markdown(
            [_cs(name="my_feature", description="A fix")],
            query="status:Ready",
        )
        assert out == snapshot("""\
# Search Results

**Query:** `status:Ready`

Found 1 change(s): 1 Ready

## my_feature

**Status:** Ready · **Project:** myproject

> A fix

""")

    def test_no_query_no_line(self) -> None:
        out = _capture_markdown([_cs(name="bare")])
        assert "**Query:**" not in out


# ---------------------------------------------------------------------------
# Commit drawer paths (CHAT/DIFF/PLAN)
# ---------------------------------------------------------------------------


class TestDrawerPaths:
    def test_commit_drawers(self) -> None:
        from pathlib import Path

        home = str(Path.home())
        out = _capture_markdown(
            [
                _cs(
                    name="with_drawers",
                    commits=[
                        CommitEntry(
                            number=1,
                            note="First commit",
                            chat=f"{home}/.sase/chats/chat.md",
                            diff=f"{home}/.sase/diffs/diff",
                            plan=f"{home}/.sase/plans/plan.md",
                        ),
                        CommitEntry(
                            number=2,
                            note="Second commit",
                            diff=f"{home}/.sase/diffs/diff2",
                        ),
                    ],
                )
            ]
        )
        assert (
            "> **1:** `~/.sase/chats/chat.md` · `~/.sase/diffs/diff`"
            " · `~/.sase/plans/plan.md`"
        ) in out
        assert "> **2:** `~/.sase/diffs/diff2`" in out

    def test_no_drawers(self) -> None:
        out = _capture_markdown(
            [
                _cs(
                    name="no_drawers",
                    commits=[CommitEntry(number=1, note="No drawers")],
                )
            ]
        )
        assert "> **1:**" not in out


# ---------------------------------------------------------------------------
# Running workspaces
# ---------------------------------------------------------------------------


class TestRunningWorkspaces:
    def test_running_workspaces(self) -> None:
        from unittest.mock import patch

        from sase.running_field import WorkspaceClaim

        mock_claims = [
            WorkspaceClaim(
                workspace_num=1, pid=12345, workflow="crs", cl_name="my_feature"
            ),
        ]
        with patch(
            "sase.running_field.get_claimed_workspaces", return_value=mock_claims
        ):
            out = _capture_markdown([_cs(name="with_ws")])
        assert "### Running Workspaces" in out
        assert "| #1 | 12345 | crs | my_feature |" in out

    def test_no_running_workspaces(self) -> None:
        from unittest.mock import patch

        with patch("sase.running_field.get_claimed_workspaces", return_value=[]):
            out = _capture_markdown([_cs(name="bare")])
        assert "### Running Workspaces" not in out


# ---------------------------------------------------------------------------
# Kickstart section
# ---------------------------------------------------------------------------


class TestKickstart:
    def test_kickstart_section(self) -> None:
        out = _capture_markdown(
            [
                _cs(
                    name="with_ks",
                    kickstart="Build a login page\n\nWith OAuth support",
                )
            ]
        )
        assert "### Kickstart" in out
        assert "> Build a login page" in out
        assert "> With OAuth support" in out

    def test_no_kickstart(self) -> None:
        out = _capture_markdown([_cs(name="bare")])
        assert "### Kickstart" not in out


# ---------------------------------------------------------------------------
# Summary anchor quick links
# ---------------------------------------------------------------------------


class TestAnchorLinks:
    def test_anchor_links_with_multiple(self) -> None:
        out = _capture_markdown(
            [
                _cs(name="feature_auth"),
                _cs(name="my_fix"),
                _cs(name="new_api"),
            ]
        )
        assert (
            "[feature_auth](#feature_auth) · [my_fix](#my_fix) · [new_api](#new_api)"
        ) in out

    def test_no_anchor_links_with_single(self) -> None:
        out = _capture_markdown([_cs(name="solo")])
        assert "[solo](#solo)" not in out
