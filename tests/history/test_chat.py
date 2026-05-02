"""Tests for the chat_history module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sase.history.chat import (
    generate_chat_filename,
    _get_branch_or_workspace_name,
    _find_resume_refs,
    _parse_flat_turns,
    get_chat_file_path,
    list_chat_histories,
    load_chat_for_resume,
    _load_chat_history,
    save_chat_history,
)

from tests.conftest import redirect_sase_home


def test_get_branch_or_workspace_name_strips_reverted_suffix() -> None:
    """Test _get_branch_or_workspace_name strips reverted suffix."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "feature_branch__3\n"

    with patch("sase.history.chat.run_shell_command", return_value=mock_result):
        result = _get_branch_or_workspace_name()
        assert result == "feature_branch"  # suffix stripped


def test_get_branch_or_workspace_name_failure() -> None:
    """Test _get_branch_or_workspace_name with failed command."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "command not found"

    with patch("sase.history.chat.run_shell_command", return_value=mock_result):
        with pytest.raises(
            RuntimeError, match="Failed to get branch_or_workspace_name"
        ):
            _get_branch_or_workspace_name()


def testgenerate_chat_filename_with_agent() -> None:
    """Test generate_chat_filename with agent name."""
    with (
        patch(
            "sase.history.chat._get_branch_or_workspace_name", return_value="my-branch"
        ),
        patch("sase.history.chat.generate_timestamp", return_value="251128_120000"),
    ):
        # User/workflow-derived filename components are sanitized.
        result = generate_chat_filename("crs", agent="planner")
        assert result == "my_branch-crs-planner-251128_120000"


def testgenerate_chat_filename_with_explicit_values() -> None:
    """Test generate_chat_filename with explicit branch and timestamp."""
    result = generate_chat_filename(
        "rerun",
        branch_or_workspace="feature-branch",
        timestamp="251128130000",
    )
    assert result == "feature_branch-rerun-251128130000"


def testgenerate_chat_filename_sanitizes_path_like_branch() -> None:
    """Path-like branch/workspace labels are kept inside one basename."""
    result = generate_chat_filename(
        "ace-run",
        branch_or_workspace="~/org",
        timestamp="260501_225009",
    )

    assert result == "__org-ace_run-260501_225009"
    assert "/" not in result


def testgenerate_chat_filename_preserves_simple_shape() -> None:
    """Simple safe names keep the established branch-workflow-timestamp shape."""
    result = generate_chat_filename(
        "ace-run",
        branch_or_workspace="feature_branch",
        timestamp="260501_225009",
    )

    assert result == "feature_branch-ace_run-260501_225009"


def testget_chat_file_path_with_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_chat_file_path returns the sharded write location for a basename."""
    redirect_sase_home(monkeypatch, tmp_path)
    result = get_chat_file_path("my-branch-run-251128_120000.md")
    # Sharded into the YYYYMM directory derived from the filename timestamp.
    assert result == str(
        tmp_path / "chats" / "202511" / "my-branch-run-251128_120000.md"
    )


def test_save_chat_history_basic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test save_chat_history creates a file with correct content."""
    redirect_sase_home(monkeypatch, tmp_path)
    with patch(
        "sase.history.chat._get_branch_or_workspace_name",
        return_value="test-branch",
    ):
        with patch(
            "sase.history.chat.generate_timestamp", return_value="251128_120000"
        ):
            result = save_chat_history(
                prompt="Hello, how are you?",
                response="I am fine, thank you!",
                workflow="run",
            )

    # ``save_chat_history`` returns a ~-prefixed path; expand before reading.
    actual_path = os.path.expanduser(result)
    assert os.path.exists(actual_path)
    with open(actual_path) as f:
        content = f.read()
    assert "Hello, how are you?" in content
    assert "I am fine, thank you!" in content
    assert "# Chat History - run" in content


def test_save_chat_history_with_path_like_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """save_chat_history can write chats for directory-style workspace labels."""
    redirect_sase_home(monkeypatch, tmp_path)

    result = save_chat_history(
        prompt="Run from org",
        response="Done",
        workflow="ace-run",
        branch_or_workspace="~/org",
        timestamp="260501_225009",
    )

    actual_path = Path(os.path.expanduser(result))
    assert actual_path == (
        tmp_path / "chats" / "202605" / "__org-ace_run-260501_225009.md"
    )
    assert actual_path.is_file()
    assert "/" not in actual_path.name


def test_save_chat_history_with_previous_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test save_chat_history with previous history prepended."""
    redirect_sase_home(monkeypatch, tmp_path)
    with patch(
        "sase.history.chat._get_branch_or_workspace_name",
        return_value="test-branch",
    ):
        with patch(
            "sase.history.chat.generate_timestamp", return_value="251128_120000"
        ):
            result = save_chat_history(
                prompt="Follow up question",
                response="Follow up answer",
                workflow="rerun",
                previous_history="Previous conversation content",
            )

    with open(os.path.expanduser(result)) as f:
        content = f.read()
    assert "Previous Conversation" in content
    assert "Previous conversation content" in content
    assert "Follow up question" in content


def test__load_chat_history_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test _load_chat_history with non-existent file."""
    redirect_sase_home(monkeypatch, tmp_path)
    with pytest.raises(FileNotFoundError):
        _load_chat_history("nonexistent-run-251128_120000")


def test_list_chat_histories_nonexistent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test list_chat_histories when directory doesn't exist."""
    # Redirect ~/.sase/ into an empty tmp_path — no chats/ subdir.
    redirect_sase_home(monkeypatch, tmp_path)
    result = list_chat_histories()
    assert result == []


def test_list_chat_histories_with_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test list_chat_histories with multiple files."""
    redirect_sase_home(monkeypatch, tmp_path)
    chats_shard = tmp_path / "chats" / "202511"
    chats_shard.mkdir(parents=True)
    (chats_shard / "test-run-251128_120000.md").write_text("content")
    (chats_shard / "test-run-251128_130000.md").write_text("content")

    result = list_chat_histories()
    assert len(result) == 2
    assert "test-run-251128_120000" in result
    assert "test-run-251128_130000" in result


def test__load_chat_history_with_increment_headings() -> None:
    """Test _load_chat_history with increment_headings=True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.md")
        content = """# Main Title

## Section 1

Some content here.

### Subsection

More content.

#### Deep section

Even more."""
        with open(test_file, "w") as f:
            f.write(content)

        result = _load_chat_history(test_file, increment_headings=True)

        # All headings should be incremented by one level
        assert "## Main Title" in result
        assert "### Section 1" in result
        assert "#### Subsection" in result
        assert "##### Deep section" in result
        # Original headings should not be present
        assert "\n# Main Title" not in result


# --- Tests for parse_chat_turns and load_chat_for_resume ---


def test_load_chat_for_resume_format() -> None:
    """Test load_chat_for_resume produces flat User/Assistant format."""
    content = """\
# Chat History - run

**Timestamp:** 2024-01-02

## Previous Conversation

## Chat History - run

**Timestamp:** 2024-01-01

### Prompt

Hello

### Response

World

---

## Prompt

Follow up

## Response

Follow up answer
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.md")
        with open(test_file, "w") as f:
            f.write(content)

        result = load_chat_for_resume(test_file)

    # Should have flat format with no markdown headings
    assert "**User:**" in result
    assert "**Assistant:**" in result
    assert "## Prompt" not in result
    assert "## Response" not in result
    assert "### Prompt" not in result

    # Content should be in chronological order
    hello_pos = result.index("Hello")
    followup_pos = result.index("Follow up")
    assert hello_pos < followup_pos

    # Turns should be separated by ---
    assert "---" in result


def test_save_chat_history_with_extra_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test save_chat_history inserts extra sections before prompt."""
    redirect_sase_home(monkeypatch, tmp_path)
    with patch(
        "sase.history.chat._get_branch_or_workspace_name",
        return_value="test-branch",
    ):
        with patch(
            "sase.history.chat.generate_timestamp", return_value="251128_120000"
        ):
            extra = "## Plan Feedback\n\n### Round 1\n> Fix the bug\n"
            result = save_chat_history(
                prompt="Fix login",
                response="Done!",
                workflow="run",
                extra_sections=extra,
            )

    with open(os.path.expanduser(result)) as f:
        content = f.read()
    # Extra sections present between timestamp and prompt
    assert "## Plan Feedback" in content
    assert "### Round 1" in content
    assert "> Fix the bug" in content
    # Verify ordering: timestamp < extra < prompt
    ts_pos = content.index("**Timestamp:**")
    extra_pos = content.index("## Plan Feedback")
    prompt_pos = content.index("## Prompt")
    assert ts_pos < extra_pos < prompt_pos


def test_parse_chat_turns_with_extra_sections() -> None:
    """Test _parse_chat_turns still works when extra sections are present."""
    from sase.history.chat import _parse_chat_turns

    content = """\
# Chat History - run

**Timestamp:** 2024-01-01

## Plan Feedback

### Round 1
> Please add tests

## Questions & Answers

### Q1: Which DB?
**Selected:** PostgreSQL

## Prompt

Fix the login bug

## Response

Done!
"""
    turns = _parse_chat_turns(content)
    assert len(turns) == 1
    assert turns[0][0] == "Fix the login bug"
    assert turns[0][1] == "Done!"


def test_load_chat_for_resume_fallback() -> None:
    """Test load_chat_for_resume falls back to raw content if no turns found."""
    content = "Just some raw text with no prompt/response structure."
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.md")
        with open(test_file, "w") as f:
            f.write(content)

        result = load_chat_for_resume(test_file)

    assert result == content


# --- Tests for _parse_flat_turns ---


def test_parse_flat_turns_basic() -> None:
    """Test _parse_flat_turns with standard input."""
    text = (
        "**User:**\n\nHello\n\n**Assistant:**\n\nWorld\n\n---\n\n"
        "**User:**\n\nHow are you?\n\n**Assistant:**\n\nFine!"
    )
    turns = _parse_flat_turns(text)
    assert len(turns) == 2
    assert turns[0] == ("Hello", "World")
    assert turns[1] == ("How are you?", "Fine!")


def test_parse_flat_turns_empty() -> None:
    """Test _parse_flat_turns with empty input."""
    assert _parse_flat_turns("") == []
    assert _parse_flat_turns("   ") == []


def test_parse_flat_turns_malformed() -> None:
    """Test _parse_flat_turns with text that has no Assistant marker."""
    text = "**User:**\n\nJust a prompt with no response"
    assert _parse_flat_turns(text) == []


# --- Tests for _find_resume_refs ---


def test_find_resume_refs_colon_syntax() -> None:
    """Test _find_resume_refs with colon syntax."""
    refs = _find_resume_refs("#resume:myagent some other text")
    assert len(refs) == 1
    assert refs[0] == ("#resume:myagent", "resume", "myagent")


def test_find_resume_refs_paren_syntax() -> None:
    """Test _find_resume_refs with paren syntax."""
    refs = _find_resume_refs("#resume(myagent)")
    assert len(refs) == 1
    assert refs[0] == ("#resume(myagent)", "resume", "myagent")


def test_find_resume_refs_backtick_quoted() -> None:
    """Test _find_resume_refs with backtick-quoted argument."""
    refs = _find_resume_refs("#resume:`my agent`")
    assert len(refs) == 1
    assert refs[0] == ("#resume:`my agent`", "resume", "my agent")


def test_find_resume_refs_resume_by_chat() -> None:
    """Test _find_resume_refs with resume_by_chat."""
    refs = _find_resume_refs("#resume_by_chat:~/.sase/chats/foo.md")
    assert len(refs) == 1
    assert refs[0] == (
        "#resume_by_chat:~/.sase/chats/foo.md",
        "resume_by_chat",
        "~/.sase/chats/foo.md",
    )


def test_find_resume_refs_no_match() -> None:
    """Test _find_resume_refs with no resume refs."""
    assert _find_resume_refs("no refs here") == []
    assert _find_resume_refs("#other:stuff") == []


def test_find_resume_refs_multiple() -> None:
    """Test _find_resume_refs with multiple refs."""
    text = "#resume:a some text #resume_by_chat:b.md"
    refs = _find_resume_refs(text)
    assert len(refs) == 2
    assert refs[0][2] == "a"
    assert refs[1][2] == "b.md"


# --- Tests for recursive resume expansion ---


def _write_chat_file(tmpdir: str, name: str, content: str) -> str:
    """Helper to write a chat file and return its path."""
    path = os.path.join(tmpdir, name)
    with open(path, "w") as f:
        f.write(content)
    return path


def test_single_level_recursive_expansion() -> None:
    """Test that a single #resume_by_chat ref gets expanded."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Chat A: the older conversation
        chat_a = _write_chat_file(
            tmpdir,
            "chat_a.md",
            "## Prompt\n\nOld question\n\n## Response\n\nOld answer\n",
        )
        # Chat B: references chat A
        chat_b = _write_chat_file(
            tmpdir,
            "chat_b.md",
            f"## Prompt\n\n#resume_by_chat:{chat_a} New question\n\n"
            f"## Response\n\nNew answer\n",
        )

        result = load_chat_for_resume(chat_b)

    turns = _parse_flat_turns(result)
    assert len(turns) == 2
    assert turns[0][0] == "Old question"
    assert turns[0][1] == "Old answer"
    assert turns[1][0] == "New question"
    assert turns[1][1] == "New answer"


def test_multi_level_chain() -> None:
    """Test A -> B -> C chain expands all levels."""
    with tempfile.TemporaryDirectory() as tmpdir:
        chat_a = _write_chat_file(
            tmpdir,
            "a.md",
            "## Prompt\n\nFirst\n\n## Response\n\nFirst reply\n",
        )
        chat_b = _write_chat_file(
            tmpdir,
            "b.md",
            f"## Prompt\n\n#resume_by_chat:{chat_a} Second\n\n"
            f"## Response\n\nSecond reply\n",
        )
        chat_c = _write_chat_file(
            tmpdir,
            "c.md",
            f"## Prompt\n\n#resume_by_chat:{chat_b} Third\n\n"
            f"## Response\n\nThird reply\n",
        )

        result = load_chat_for_resume(chat_c)

    turns = _parse_flat_turns(result)
    assert len(turns) == 3
    assert turns[0][0] == "First"
    assert turns[1][0] == "Second"
    assert turns[2][0] == "Third"


def test_cycle_detection() -> None:
    """Test that cycles don't cause infinite recursion."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path_a = os.path.join(tmpdir, "a.md")
        path_b = os.path.join(tmpdir, "b.md")

        # A references B, B references A
        with open(path_a, "w") as f:
            f.write(
                f"## Prompt\n\n#resume_by_chat:{path_b} Question A\n\n"
                f"## Response\n\nAnswer A\n"
            )
        with open(path_b, "w") as f:
            f.write(
                f"## Prompt\n\n#resume_by_chat:{path_a} Question B\n\n"
                f"## Response\n\nAnswer B\n"
            )

        # Should not hang — cycle is broken by _visited
        result = load_chat_for_resume(path_a)

    turns = _parse_flat_turns(result)
    # B is loaded (not in visited yet when A processes it), but A is skipped when B tries to load it
    assert len(turns) == 2


def test_fallback_to_previous_conversation() -> None:
    """Test fallback to ## Previous Conversation when agent not found."""
    with tempfile.TemporaryDirectory() as tmpdir:
        chat = _write_chat_file(
            tmpdir,
            "chat.md",
            "## Previous Conversation\n\n"
            "**User:**\n\nOld prompt\n\n**Assistant:**\n\nOld response\n\n"
            "---\n\n"
            "## Prompt\n\n#resume:nonexistent_agent New prompt\n\n"
            "## Response\n\nNew response\n",
        )

        with patch(
            "sase.agent.names.find_named_agent",
            return_value=None,
        ):
            result = load_chat_for_resume(chat)

    turns = _parse_flat_turns(result)
    assert len(turns) == 2
    assert turns[0][0] == "Old prompt"
    assert turns[1][0] == "New prompt"


def test_resume_by_chat_expansion() -> None:
    """Test #resume_by_chat:path expansion works end-to-end."""
    with tempfile.TemporaryDirectory() as tmpdir:
        older = _write_chat_file(
            tmpdir,
            "older.md",
            "## Prompt\n\nEarlier question\n\n## Response\n\nEarlier answer\n",
        )
        newer = _write_chat_file(
            tmpdir,
            "newer.md",
            f"## Prompt\n\n#resume_by_chat:{older} Later question\n\n"
            f"## Response\n\nLater answer\n",
        )

        result = load_chat_for_resume(newer)

    assert "Earlier question" in result
    assert "Later question" in result
    assert "#resume_by_chat" not in result


def test_prompt_text_cleanup() -> None:
    """Test that #resume ref is stripped but surrounding text preserved."""
    with tempfile.TemporaryDirectory() as tmpdir:
        older = _write_chat_file(
            tmpdir,
            "older.md",
            "## Prompt\n\nOld\n\n## Response\n\nOld reply\n",
        )
        newer = _write_chat_file(
            tmpdir,
            "newer.md",
            f"## Prompt\n\n#gh:sase #resume_by_chat:{older} Let's continue.\n\n"
            f"## Response\n\nContinued!\n",
        )

        result = load_chat_for_resume(newer)

    turns = _parse_flat_turns(result)
    last_prompt = turns[-1][0]
    assert "#resume_by_chat" not in last_prompt
    assert "#gh:sase" in last_prompt
    assert "Let's continue." in last_prompt
