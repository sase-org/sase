"""Tests for markdown rendering in search handler."""

from pathlib import Path

import pytest

from sase.ace.changespec import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
    TimestampEntry,
)
from sase.main.search_handler import _display_markdown
from sase.running_field import WorkspaceClaim


def test_display_markdown_renders_summary_and_minimal_changespec(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Markdown summary and core fields render for a minimal ChangeSpec."""
    home = str(Path.home())
    changespec = ChangeSpec(
        name="feature_search",
        description="Find related work.",
        parent=None,
        cl=None,
        status="Ready",
        test_targets=None,
        kickstart=None,
        file_path=f"{home}/.sase/projects/demo/demo.gp",
        line_number=12,
    )

    _display_markdown([changespec], query="status:Ready")
    output = capsys.readouterr().out

    assert "# Search Results" in output
    assert "- Query: `status:Ready`" in output
    assert "- Total matches: `1`" in output
    assert "- Status breakdown: `Ready: 1`" in output
    assert "## 1. feature\\_search" in output
    assert "| Status (`STATUS`) | `Ready` |" in output
    assert (
        "| Project File (`file:line`) | `~/.sase/projects/demo/demo.gp:12` |" in output
    )
    assert "### Purpose (`DESCRIPTION`)" in output
    assert "Find related work." in output
    assert "### Kickstart (`KICKSTART`)" not in output
    assert "### Commits (`COMMITS`)" not in output
    assert "### Timeline (`TIMESTAMPS`)" not in output


def test_display_markdown_renders_optional_sections_and_escapes_content(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Markdown renderer includes optional sections and escapes markdown-sensitive text."""
    home = str(Path.home())
    changespec = ChangeSpec(
        name="feature_[alpha]|core",
        description="line 1\nline *2* with `code`",
        parent="parent_feature",
        cl="https://example.test/cl/123",
        status="Draft",
        test_targets=["//pkg:all", "None"],
        kickstart="run this\nthen validate",
        file_path=f"{home}/.sase/projects/demo/demo.gp",
        line_number=45,
        bug="b/12345",
        commits=[
            CommitEntry(
                number=2,
                note="Fix parser | output",
                chat=f"{home}/.sase/chats/chat.md",
                diff=f"{home}/.sase/diffs/fix.diff",
                plan=f"{home}/.sase/plans/plan.md",
                suffix="NEW PROPOSAL",
                suffix_type="plain",
            )
        ],
        hooks=[
            HookEntry(
                command="!$pytest -q",
                status_lines=[
                    HookStatusLine(
                        commit_entry_num="2",
                        timestamp="260401_120000",
                        status="FAILED",
                        duration="5s",
                        suffix="Hook Command Failed",
                        suffix_type="error",
                    )
                ],
            )
        ],
        comments=[
            CommentEntry(
                reviewer="critique",
                file_path=f"{home}/.sase/comments/review.json",
                suffix="Unresolved Critique Comments",
                suffix_type="error",
            )
        ],
        mentors=[
            MentorEntry(
                entry_id="2",
                profiles=["default_profile"],
                status_lines=[
                    MentorStatusLine(
                        profile_name="default_profile",
                        mentor_name="safety",
                        status="COMMENTED",
                        timestamp="260401_121500",
                        duration="33s",
                        suffix="mentor_complete-123-260401_121500",
                        suffix_type="running_agent",
                    )
                ],
            )
        ],
        timestamps=[
            TimestampEntry(
                timestamp="2026-04-01 12:15:00",
                event_type="STATUS",
                detail="WIP -> Draft",
            )
        ],
    )

    monkeypatch.setattr(
        "sase.running_field.get_claimed_workspaces",
        lambda _path: [
            WorkspaceClaim(
                workspace_num=7,
                workflow="run",
                cl_name="feature_[alpha]|core",
                pid=4242,
            )
        ],
    )

    _display_markdown([changespec], query="name:feature_[alpha]|core")
    output = capsys.readouterr().out

    assert "- Query: `name:feature\\_\\[alpha\\]\\|core`" in output
    assert "| Parent (`PARENT`) | `parent\\_feature` |" in output
    assert "| CL/PR (`CL`) | `https://example.test/cl/123` |" in output
    assert "| Bug (`BUG`) | `b/12345` |" in output
    assert "```text" in output
    assert "line *2* with `code`" in output
    assert "### Kickstart (`KICKSTART`)" in output
    assert "### Test Targets (`TEST TARGETS`)" in output
    assert "- `//pkg:all`" in output
    assert "### Running Workspaces (`RUNNING`)" in output
    assert "`\\#7` | `4242` | `run` | `feature\\_\\[alpha\\]\\|core`" in output
    assert "### Commits (`COMMITS`)" in output
    assert "`CHAT`: `~/.sase/chats/chat.md`" in output
    assert "`DIFF`: `~/.sase/diffs/fix.diff`" in output
    assert "`PLAN`: `~/.sase/plans/plan.md`" in output
    assert "status suffix: `NEW PROPOSAL`, type: `plain`" in output
    assert "### Hooks (`HOOKS`)" in output
    assert "| `pytest -q` | `2` | `\\[260401\\_120000\\]` | `FAILED` | `5s` |" in output
    assert "`Hook Command Failed` (type: `error`)" in output
    assert "### Comments (`COMMENTS`)" in output
    assert "`[critique]` `~/.sase/comments/review.json`" in output
    assert "### Mentors (`MENTORS`)" in output
    assert "Entry `(2)` profiles: default\\_profile" in output
    assert "`default\\_profile:safety` -> `COMMENTED`" in output
    assert "timestamp `\\[260401\\_121500\\]`" in output
    assert "### Timeline (`TIMESTAMPS`)" in output
    assert "| `2026-04-01 12:15:00` | `STATUS` | `WIP -> Draft` |" in output
