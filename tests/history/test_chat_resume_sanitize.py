"""Tests for sase-lingo sanitization of #fork resume history."""

import tempfile
from pathlib import Path

from sase.history.chat import (
    _parse_flat_turns,
    _sanitize_resume_prompt,
    load_chat_for_resume,
)


def _write_chat_file(tmpdir: str, name: str, content: str) -> str:
    path = Path(tmpdir) / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_sanitize_strips_directives_refs_and_jinja() -> None:
    """Directives, #/#! references, and Jinja markers are all removed."""
    prompt = (
        "%name:@.cld %wait:research.cdx-32 %t:research\n\n"
        "#git:home The two independent research agents have finished.\n\n"
        "{{ wait_chats }}\n\n"
        "Read both chat transcripts first."
    )
    result = _sanitize_resume_prompt(prompt)

    assert "%name" not in result
    assert "%wait" not in result
    assert "%t:" not in result
    assert "#git:home" not in result
    assert "{{ wait_chats }}" not in result
    assert "The two independent research agents have finished." in result
    assert "Read both chat transcripts first." in result
    # No orphaned leading whitespace left from removed references.
    assert "\n " not in result
    assert not result.startswith(" ")


def test_sanitize_strips_tribe_fork_reference() -> None:
    result = _sanitize_resume_prompt("#fork:@epic Continue from the result.")

    assert result == "Continue from the result."


def test_sanitize_preserves_fenced_code() -> None:
    """%, #, and {{ }} inside fenced code blocks are preserved verbatim."""
    prompt = (
        "Look at this example:\n\n"
        "```\n"
        "%name:foo\n"
        "#git:home\n"
        "{{ wait_chats }}\n"
        "```\n\n"
        "%auto done"
    )
    result = _sanitize_resume_prompt(prompt)

    assert "%name:foo" in result
    assert "#git:home" in result
    assert "{{ wait_chats }}" in result
    assert "%auto" not in result
    assert result.rstrip().endswith("done")


def test_sanitize_preserves_markdown_heading() -> None:
    """A real markdown heading (# Title) is preserved."""
    prompt = "# Title\n\nSome body text."
    result = _sanitize_resume_prompt(prompt)
    assert "# Title" in result
    assert "Some body text." in result


def test_sanitize_is_idempotent() -> None:
    """Sanitizing already-clean text changes nothing."""
    prompt = "%name:foo #git:home Just do the work."
    once = _sanitize_resume_prompt(prompt)
    assert _sanitize_resume_prompt(once) == once


def test_sanitize_empty() -> None:
    """Empty input is returned unchanged."""
    assert _sanitize_resume_prompt("") == ""


def test_resume_user_block_is_sanitized() -> None:
    """load_chat_for_resume emits a clean **User:** block, untouched response."""
    with tempfile.TemporaryDirectory() as tmpdir:
        chat = _write_chat_file(
            tmpdir,
            "chat.md",
            "## Prompt\n\n"
            "%name:foo %wait:bar %t:research\n\n"
            "#git:home Continue the work.\n\n"
            "{{ wait_chats }}\n\n"
            "## Response\n\n"
            "I used %name and #git internally; this stays.\n",
        )

        result = load_chat_for_resume(chat)

    turns = _parse_flat_turns(result)
    assert len(turns) == 1
    prompt, response = turns[0]
    assert "%name" not in prompt
    assert "#git:home" not in prompt
    assert "{{ wait_chats }}" not in prompt
    assert "Continue the work." in prompt
    # Assistant response is left untouched even though it mentions the lingo.
    assert "%name" in response
    assert "#git" in response


def test_fork_of_a_fork_is_fully_clean() -> None:
    """Nested previous-conversation turns carry no leaked sase lingo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        older = _write_chat_file(
            tmpdir,
            "older.md",
            "## Prompt\n\n%name:a #git:home Earlier task.\n\n"
            "## Response\n\nEarlier reply.\n",
        )
        newer = _write_chat_file(
            tmpdir,
            "newer.md",
            f"## Prompt\n\n%name:b %wait:a #fork_by_chat:{older} "
            f"Later task.\n\n## Response\n\nLater reply.\n",
        )

        result = load_chat_for_resume(newer)

    assert "%name" not in result
    assert "%wait" not in result
    assert "#git:home" not in result
    assert "#fork_by_chat" not in result
    turns = _parse_flat_turns(result)
    assert [t[0] for t in turns] == ["Earlier task.", "Later task."]
