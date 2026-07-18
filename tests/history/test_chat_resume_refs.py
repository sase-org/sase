"""Tests for chat resume references and recursive expansion."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.history.chat import (
    _find_resume_refs,
    _parse_flat_turns,
    _resolve_resume_to_chat_path,
    load_chat_for_resume,
)

from tests._agent_names_fixtures import make_agent


def test_find_resume_refs_colon_syntax() -> None:
    """Test _find_resume_refs with colon syntax."""
    refs = _find_resume_refs("#fork:myagent some other text")
    assert len(refs) == 1
    assert refs[0] == ("#fork:myagent", "fork", "myagent")


def test_find_resume_refs_paren_syntax() -> None:
    """Test _find_resume_refs with paren syntax."""
    refs = _find_resume_refs("#fork(myagent)")
    assert len(refs) == 1
    assert refs[0] == ("#fork(myagent)", "fork", "myagent")


def test_find_resume_refs_backtick_quoted() -> None:
    """Test _find_resume_refs with backtick-quoted argument."""
    refs = _find_resume_refs("#fork:`my agent`")
    assert len(refs) == 1
    assert refs[0] == ("#fork:`my agent`", "fork", "my agent")


def test_find_resume_refs_tribe_target() -> None:
    assert _find_resume_refs("#fork:@epic Continue") == [
        ("#fork:@epic", "fork", "@epic")
    ]


def test_find_resume_refs_legacy_resume() -> None:
    """Historical chat transcripts can still contain legacy #resume refs."""
    refs = _find_resume_refs("#resume:myagent #resume_by_chat:old.md")
    assert refs == [
        ("#resume:myagent", "resume", "myagent"),
        ("#resume_by_chat:old.md", "resume_by_chat", "old.md"),
    ]


def test_find_resume_refs_fork_by_chat() -> None:
    """Test _find_resume_refs with fork_by_chat."""
    refs = _find_resume_refs("#fork_by_chat:~/.sase/chats/foo.md")
    assert len(refs) == 1
    assert refs[0] == (
        "#fork_by_chat:~/.sase/chats/foo.md",
        "fork_by_chat",
        "~/.sase/chats/foo.md",
    )


def test_find_resume_refs_no_match() -> None:
    """Test _find_resume_refs with no resume refs."""
    assert _find_resume_refs("no refs here") == []
    assert _find_resume_refs("#other:stuff") == []


def test_find_resume_refs_multiple() -> None:
    """Test _find_resume_refs with multiple refs."""
    text = "#fork:a some text #fork_by_chat:b.md"
    refs = _find_resume_refs(text)
    assert len(refs) == 2
    assert refs[0][2] == "a"
    assert refs[1][2] == "b.md"


def test_find_resume_refs_flattens_multi_parent_fork_syntaxes() -> None:
    assert _find_resume_refs("#fork:planner,coder New query") == [
        ("#fork:planner,coder", "fork", "planner"),
        ("#fork:planner,coder", "fork", "coder"),
    ]
    assert _find_resume_refs("#fork(planner, coder) New query") == [
        ("#fork(planner, coder)", "fork", "planner"),
        ("#fork(planner, coder)", "fork", "coder"),
    ]


def _write_chat_file(tmpdir: str, name: str, content: str) -> str:
    """Helper to write a chat file and return its path."""
    path = Path(tmpdir) / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_single_level_recursive_expansion() -> None:
    """Test that a single #fork_by_chat ref gets expanded."""
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
            f"## Prompt\n\n#fork_by_chat:{chat_a} New question\n\n"
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
            f"## Prompt\n\n#fork_by_chat:{chat_a} Second\n\n"
            f"## Response\n\nSecond reply\n",
        )
        chat_c = _write_chat_file(
            tmpdir,
            "c.md",
            f"## Prompt\n\n#fork_by_chat:{chat_b} Third\n\n"
            f"## Response\n\nThird reply\n",
        )

        result = load_chat_for_resume(chat_c)

    turns = _parse_flat_turns(result)
    assert len(turns) == 3
    assert turns[0][0] == "First"
    assert turns[1][0] == "Second"
    assert turns[2][0] == "Third"


def test_multi_parent_expansion_loads_every_parent_in_order() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        planner = _write_chat_file(
            tmpdir,
            "planner.md",
            "## Prompt\n\nPlan\n\n## Response\n\nPlan reply\n",
        )
        coder = _write_chat_file(
            tmpdir,
            "coder.md",
            "## Prompt\n\nCode\n\n## Response\n\nCode reply\n",
        )
        merged = _write_chat_file(
            tmpdir,
            "merged.md",
            "## Prompt\n\n#fork:planner,coder Merge\n\n## Response\n\nMerged reply\n",
        )
        paths = {"planner": planner, "coder": coder}
        with patch(
            "sase.history.chat._resolve_resume_to_chat_path",
            side_effect=lambda _kind, argument: paths.get(argument),
        ):
            result = load_chat_for_resume(merged)

    turns = _parse_flat_turns(result)
    assert [prompt for prompt, _ in turns] == ["Plan", "Code", "Merge"]


def test_multi_parent_expansion_preserves_shared_ancestry_per_parent() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        shared = _write_chat_file(
            tmpdir,
            "shared.md",
            "## Prompt\n\nShared\n\n## Response\n\nShared reply\n",
        )
        planner = _write_chat_file(
            tmpdir,
            "planner.md",
            f"## Prompt\n\n#fork_by_chat:{shared} Plan\n\n## Response\n\nPlan reply\n",
        )
        coder = _write_chat_file(
            tmpdir,
            "coder.md",
            f"## Prompt\n\n#fork_by_chat:{shared} Code\n\n## Response\n\nCode reply\n",
        )
        merged = _write_chat_file(
            tmpdir,
            "merged.md",
            "## Prompt\n\n#fork(planner, coder) Merge\n\n## Response\n\nMerged reply\n",
        )

        def resolve(kind: str, argument: str) -> str | None:
            if kind == "fork_by_chat":
                return argument
            return {"planner": planner, "coder": coder}.get(argument)

        with patch(
            "sase.history.chat._resolve_resume_to_chat_path", side_effect=resolve
        ):
            result = load_chat_for_resume(merged)

    turns = _parse_flat_turns(result)
    assert [prompt for prompt, _ in turns] == [
        "Shared",
        "Plan",
        "Shared",
        "Code",
        "Merge",
    ]


def test_cycle_detection() -> None:
    """Test that cycles don't cause infinite recursion."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path_a = Path(tmpdir) / "a.md"
        path_b = Path(tmpdir) / "b.md"

        # A references B, B references A
        path_a.write_text(
            f"## Prompt\n\n#fork_by_chat:{path_b} Question A\n\n"
            f"## Response\n\nAnswer A\n",
            encoding="utf-8",
        )
        path_b.write_text(
            f"## Prompt\n\n#fork_by_chat:{path_a} Question B\n\n"
            f"## Response\n\nAnswer B\n",
            encoding="utf-8",
        )

        # Should not hang -- cycle is broken by _visited
        result = load_chat_for_resume(str(path_a))

    turns = _parse_flat_turns(result)
    # B is loaded (not in visited yet when A processes it), but A is skipped when
    # B tries to load it.
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
            "## Prompt\n\n#fork:nonexistent_agent New prompt\n\n"
            "## Response\n\nNew response\n",
        )

        with patch("sase.agent.names.resolve_resume_agent_name", return_value=None):
            result = load_chat_for_resume(chat)

    turns = _parse_flat_turns(result)
    assert len(turns) == 2
    assert turns[0][0] == "Old prompt"
    assert turns[1][0] == "New prompt"


def test_fallback_to_previous_conversations_recovers_plural_envelope_once() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        chat = _write_chat_file(
            tmpdir,
            "chat.md",
            "# Previous Conversations\n\n"
            "## Conversation 1 of 2 — agent `planner`\n\n"
            "**User:**\n\nOld plan\n\n**Assistant:**\n\nPlan reply\n\n"
            "## Conversation 2 of 2 — agent `coder`\n\n"
            "**User:**\n\nOld code\n\n**Assistant:**\n\nCode reply\n\n"
            "# New Query\n\n"
            "## Prompt\n\n#fork:missing-a,missing-b New prompt\n\n"
            "## Response\n\nNew response\n",
        )

        with patch("sase.history.chat._resolve_resume_to_chat_path", return_value=None):
            result = load_chat_for_resume(chat)

    turns = _parse_flat_turns(result)
    assert [prompt for prompt, _ in turns] == ["Old plan", "Old code", "New prompt"]


def test_resume_agent_family_resolves_to_latest_completed_member_chat(
    tmp_path: Path,
    monkeypatch,
) -> None:
    chat_dir = tmp_path / ".sase" / "chats"
    chat_dir.mkdir(parents=True)
    planner_chat = chat_dir / "planner.md"
    planner_chat.write_text("planner", encoding="utf-8")
    coder_chat = chat_dir / "coder.md"
    coder_chat.write_text("coder", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "family",
        workflow_name="family",
        agent_family="family",
        role_suffix="-plan",
        done=True,
        outcome="completed",
        response_path=str(planner_chat),
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "family-code",
        workflow_name="family",
        agent_family="family",
        role_suffix="-code",
        parent_timestamp="20260506010101",
        done=True,
        outcome="completed",
        response_path=str(coder_chat),
    )

    assert _resolve_resume_to_chat_path("fork", "family") == str(coder_chat)


def test_template_resume_ref_resolves_latest_concrete_agent_chat(
    tmp_path: Path,
    monkeypatch,
) -> None:
    chat_dir = tmp_path / ".sase" / "chats"
    chat_dir.mkdir(parents=True)
    older_chat = chat_dir / "older.md"
    older_chat.write_text("older", encoding="utf-8")
    newer_chat = chat_dir / "newer.md"
    newer_chat.write_text("newer", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "build-1",
        done=True,
        outcome="completed",
        response_path=str(older_chat),
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "build-3",
        done=True,
        outcome="completed",
        response_path=str(newer_chat),
    )

    assert _resolve_resume_to_chat_path("resume", "build-@") == str(newer_chat)


def test_template_suffix_resume_ref_resolves_latest_concrete_agent_chat(
    tmp_path: Path,
    monkeypatch,
) -> None:
    chat_dir = tmp_path / ".sase" / "chats"
    chat_dir.mkdir(parents=True)
    older_chat = chat_dir / "older.md"
    older_chat.write_text("older", encoding="utf-8")
    newer_chat = chat_dir / "newer.md"
    newer_chat.write_text("newer", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "cld.0",
        done=True,
        outcome="completed",
        response_path=str(older_chat),
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "cld.1",
        done=True,
        outcome="completed",
        response_path=str(newer_chat),
    )

    assert _resolve_resume_to_chat_path("fork", "cld.@") == str(newer_chat)


def test_tribe_resume_ref_is_left_for_prompt_sanitization() -> None:
    assert _resolve_resume_to_chat_path("fork", "@epic") is None


def test_fork_by_chat_expansion() -> None:
    """Test #fork_by_chat:path expansion works end-to-end."""
    with tempfile.TemporaryDirectory() as tmpdir:
        older = _write_chat_file(
            tmpdir,
            "older.md",
            "## Prompt\n\nEarlier question\n\n## Response\n\nEarlier answer\n",
        )
        newer = _write_chat_file(
            tmpdir,
            "newer.md",
            f"## Prompt\n\n#fork_by_chat:{older} Later question\n\n"
            f"## Response\n\nLater answer\n",
        )

        result = load_chat_for_resume(newer)

    assert "Earlier question" in result
    assert "Later question" in result
    assert "#fork_by_chat" not in result


def test_prompt_text_cleanup() -> None:
    """The #fork ref and other sase lingo are stripped; prose is preserved."""
    with tempfile.TemporaryDirectory() as tmpdir:
        older = _write_chat_file(
            tmpdir,
            "older.md",
            "## Prompt\n\nOld\n\n## Response\n\nOld reply\n",
        )
        newer = _write_chat_file(
            tmpdir,
            "newer.md",
            f"## Prompt\n\n#gh:sase #fork_by_chat:{older} Let's continue.\n\n"
            f"## Response\n\nContinued!\n",
        )

        result = load_chat_for_resume(newer)

    turns = _parse_flat_turns(result)
    last_prompt = turns[-1][0]
    # All sase references are sanitized away, leaving only the natural prose.
    assert "#fork_by_chat" not in last_prompt
    assert "#gh:sase" not in last_prompt
    assert "Let's continue." in last_prompt
