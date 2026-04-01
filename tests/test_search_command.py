"""Tests for the `sase search` command parser and handlers."""

import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.ace.changespec import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
)
from sase.main.parser import create_parser
from sase.main.search_handler import _display_markdown, handle_search_command


def _make_minimal_changespec() -> ChangeSpec:
    return ChangeSpec(
        name="alpha",
        description="basic description",
        parent=None,
        cl=None,
        status="WIP",
        test_targets=None,
        kickstart=None,
        file_path=f"{Path.home()}/.sase/projects/proj/proj.gp",
        line_number=7,
    )


def _make_full_changespec() -> ChangeSpec:
    return ChangeSpec(
        name="feature alpha",
        description="Line one\nLine two",
        parent="base-change",
        cl="https://example.com/pr/123",
        status="Ready",
        test_targets=["pytest tests/test_x.py", "None"],
        kickstart="Run `just test`",
        file_path=f"{Path.home()}/.sase/projects/proj/proj.gp",
        line_number=42,
        bug="https://bugs.example.com/101",
        commits=[
            CommitEntry(
                number=2,
                note="Implement [core] *feature*",
                chat=f"{Path.home()}/.sase/chats/chat_1.md",
                diff=f"{Path.home()}/.sase/xcmds/diff_1.diff",
                suffix="251231_120000",
            )
        ],
        hooks=[
            HookEntry(
                command="!pytest -q",
                status_lines=[
                    HookStatusLine(
                        commit_entry_num="2",
                        timestamp="260101_010203",
                        status="FAILED",
                        duration="12s",
                        suffix="Hook Command Failed",
                    )
                ],
            )
        ],
        comments=[
            CommentEntry(
                reviewer="critique",
                file_path=f"{Path.home()}/.sase/comments/feature-alpha.json",
                suffix="2",
            )
        ],
        mentors=[
            MentorEntry(
                entry_id="2",
                profiles=["default", "security"],
                status_lines=[
                    MentorStatusLine(
                        profile_name="default",
                        mentor_name="style",
                        status="PASSED",
                        timestamp="260101_020304",
                        duration="20s",
                    )
                ],
            )
        ],
    )


def test_search_parser_accepts_markdown_format() -> None:
    parser = create_parser()
    args = parser.parse_args(["search", "foo", "--format", "markdown"])
    assert args.command == "search"
    assert args.query == "foo"
    assert args.format == "markdown"


def test_display_markdown_renders_full_structure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cs = _make_full_changespec()
    running_claim = SimpleNamespace(
        workspace_num=3, pid=54321, workflow="crs", cl_name="feature alpha"
    )

    with (
        patch(
            "sase.running_field.get_claimed_workspaces", return_value=[running_claim]
        ),
        patch("sase.workspace_provider.get_change_label", return_value="PR"),
    ):
        _display_markdown([cs], 'status:"Ready"')

    out = capsys.readouterr().out
    assert "# ChangeSpec Search Results" in out
    assert '**Query:** `status:"Ready"`' in out
    assert "**Matches:** 1" in out
    assert '<a id="feature-alpha"></a>' in out
    assert "## feature alpha" in out
    assert "- **Status:** Ready" in out
    assert "- **Path:** `~/.sase/projects/proj/proj.gp:42`" in out
    assert "- **Parent:** base\\-change" in out
    assert "- **PR:** https://example.com/pr/123" in out
    assert "- **Bug:** https://bugs.example.com/101" in out
    assert "- **Test Targets:** pytest tests/test\\_x.py" in out
    assert "### Description" in out
    assert "> Line one" in out
    assert "### Kickstart" in out
    assert "> Run `just test`" in out
    assert "### Running" in out
    assert "| Workspace | PID | Workflow | ChangeSpec |" in out
    assert "| #3 | 54321 | crs | feature alpha |" in out
    assert "### Commits" in out
    assert "- (2) Implement \\[core\\] \\*feature\\* - (251231\\_120000)" in out
    assert "  - `CHAT:` `~/.sase/chats/chat_1.md`" in out
    assert "  - `DIFF:` `~/.sase/xcmds/diff_1.diff`" in out
    assert "### Hooks" in out
    assert "- `!pytest -q`" in out
    assert "  - (2) [260101_010203] FAILED (12s) - (Hook Command Failed)" in out
    assert "### Comments" in out
    assert "- [critique] `~/.sase/comments/feature-alpha.json` - (2)" in out
    assert "### Mentors" in out
    assert "- (2) default security" in out
    assert "  - [260101_020304] default:style - PASSED - (20s)" in out
    assert "## Summary" in out
    assert "### Status Breakdown" in out
    assert "- Ready: 1" in out
    assert "### Quick Links" in out
    assert "- [feature alpha](#feature-alpha)" in out


def test_display_markdown_omits_empty_optional_sections(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cs = _make_minimal_changespec()

    with patch("sase.running_field.get_claimed_workspaces", return_value=[]):
        _display_markdown([cs], "alpha")

    out = capsys.readouterr().out
    assert "### Description" in out
    assert "### Kickstart" not in out
    assert "### Running" not in out
    assert "### Commits" not in out
    assert "### Hooks" not in out
    assert "### Comments" not in out
    assert "### Mentors" not in out
    assert "- **Parent:**" not in out
    assert "- **CL:**" not in out
    assert "- **PR:**" not in out
    assert "- **Bug:**" not in out
    assert "- **Test Targets:**" not in out


@pytest.mark.parametrize(
    ("fmt", "expected_attr"),
    [
        ("plain", "_display_plain"),
        ("rich", "_display_rich"),
        ("markdown", "_display_markdown"),
    ],
)
def test_handle_search_dispatches_by_format(fmt: str, expected_attr: str) -> None:
    args = argparse.Namespace(query="alpha", format=fmt)
    cs = _make_minimal_changespec()

    with (
        patch("sase.ace.query.parse_query", return_value=object()),
        patch("sase.ace.changespec.find_all_changespecs", return_value=[cs]),
        patch("sase.ace.query.evaluate_query", return_value=True),
        patch("sase.main.search_handler._display_plain") as mock_plain,
        patch("sase.main.search_handler._display_rich") as mock_rich,
        patch("sase.main.search_handler._display_markdown") as mock_markdown,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_search_command(args)

    assert exc_info.value.code == 0
    if expected_attr == "_display_plain":
        mock_plain.assert_called_once_with([cs])
        mock_rich.assert_not_called()
        mock_markdown.assert_not_called()
    elif expected_attr == "_display_rich":
        mock_rich.assert_called_once_with([cs])
        mock_plain.assert_not_called()
        mock_markdown.assert_not_called()
    else:
        mock_markdown.assert_called_once_with([cs], "alpha")
        mock_plain.assert_not_called()
        mock_rich.assert_not_called()
