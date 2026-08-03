"""Tests for saving chat history transcripts."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from sase.history.chat import _parse_chat_turns, save_chat_history

from tests.conftest import redirect_sase_home


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
    assert "- **MODEL:**" not in content
    assert "- **AGENT:**" not in content
    assert "- **PROMPT:**" not in content


def test_save_chat_history_writes_single_prompt_section_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path)

    result = save_chat_history(
        prompt="Use #plan.\n\n## Details\n\nKeep this heading in the prompt.",
        response="Done",
        workflow="ace-run",
        branch_or_workspace="branch",
        timestamp="260501_225009",
    )

    content = Path(os.path.expanduser(result)).read_text(encoding="utf-8")
    assert "<!-- sase:section:" not in content
    assert content.count("\n## Prompt\n\n") == 1
    assert _parse_chat_turns(content) == [
        ("Use #plan.\n\n## Details\n\nKeep this heading in the prompt.", "Done")
    ]


def test_save_chat_history_with_transcript_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Metadata fields are rendered as a compact bullet list before the prompt."""
    redirect_sase_home(monkeypatch, tmp_path)
    with (
        patch(
            "sase.history.chat._get_branch_or_workspace_name",
            return_value="test-branch",
        ),
        patch("sase.history.chat.generate_timestamp", return_value="251128_120000"),
    ):
        result = save_chat_history(
            prompt="Implement the plan",
            response="Done",
            workflow="ace-run",
            metadata_model="claude-sonnet",
            metadata_llm_provider="claude",
            metadata_agent="alpha",
            metadata_multi_agent_prompt="~/.sase/multi_prompts/202606/p.md",
        )

    content = Path(os.path.expanduser(result)).read_text(encoding="utf-8")
    assert "**Timestamp:**" not in content
    assert "**Timestamp** " not in content
    assert "\n\n- **TIMESTAMP:** " in content
    assert "- **MODEL:** claude/claude-sonnet\n" in content
    assert "- **AGENT:** alpha\n" in content
    assert "- **PROMPT:** `~/.sase/multi_prompts/202606/p.md`\n\n" in content
    assert "\n\n- **MODEL:**" not in content
    assert "\n\n- **AGENT:**" not in content
    assert content.index("- **TIMESTAMP:**") < content.index("- **MODEL:**")
    assert content.index("- **MODEL:**") < content.index("- **AGENT:**")
    assert content.index("- **AGENT:**") < content.index("- **PROMPT:**")
    assert content.index("- **PROMPT:**") < content.index("## Prompt")


def test_save_chat_history_filename_agent_can_differ_from_metadata_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The legacy agent kwarg still controls path/header only."""
    redirect_sase_home(monkeypatch, tmp_path)

    result = save_chat_history(
        prompt="Plan",
        response="Approved",
        workflow="ace-run",
        agent="planner-role",
        branch_or_workspace="branch",
        timestamp="260501_225009",
        metadata_agent="sase-agent-plan",
    )

    actual_path = Path(os.path.expanduser(result))
    content = actual_path.read_text(encoding="utf-8")
    assert actual_path.name == "branch-ace_run-planner_role-260501_225009.md"
    assert "# Chat History - ace-run (planner-role)" in content
    assert "- **AGENT:** sase-agent-plan" in content


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
    ts_pos = content.index("**TIMESTAMP:**")
    extra_pos = content.index("## Plan Feedback")
    prompt_pos = content.index("## Prompt")
    assert ts_pos < extra_pos < prompt_pos
