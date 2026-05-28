from __future__ import annotations

from pathlib import Path

from sase.memory.episodes.chat_parse import (
    CHAT_EXCERPT_MAX_CHARS,
    parse_chat_transcript,
)


def test_parse_chat_transcript_extracts_turns_links_and_fork_refs(
    tmp_path: Path,
) -> None:
    linked = tmp_path / "linked.md"
    linked.write_text("## Prompt\n\nEarlier\n\n## Response\n\nEarlier answer\n")
    long_prompt = "word " * 100
    chat = tmp_path / "chat.md"
    chat.write_text(
        "# Chat History - run\n\n"
        "**Timestamp** 2026-05-26 12:00:00 UTC\n\n"
        "## Linked Chats\n\n"
        f"- 1. plan - `{linked}`\n\n"
        "## Prompt\n\n"
        f"#fork_by_chat:{linked} {long_prompt}\n\n"
        "## Response\n\n"
        "A compact answer.\n",
        encoding="utf-8",
    )

    parsed = parse_chat_transcript(chat)

    assert parsed.path == str(chat.resolve())
    assert parsed.linked_chat_paths == [str(linked.resolve())]
    assert len(parsed.fork_refs) == 1
    assert parsed.fork_refs[0].xprompt_name == "fork_by_chat"
    assert parsed.fork_refs[0].resolved_chat_path == str(linked.resolve())
    assert len(parsed.turns) == 1
    assert parsed.turns[0].prompt_excerpt is not None
    assert len(parsed.turns[0].prompt_excerpt) <= CHAT_EXCERPT_MAX_CHARS
    assert parsed.turns[0].response_excerpt == "A compact answer."
