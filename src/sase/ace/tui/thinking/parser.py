"""JSONL transcript parser for extracting Claude thinking blocks."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Files larger than this use tail-seeking optimization
_TAIL_THRESHOLD = 500 * 1024  # 500 KB


@dataclass
class ThinkingBlock:
    """A single thinking block extracted from a conversation transcript."""

    text: str
    timestamp: str
    index: int  # 1-based position (chronological)
    following_action: str | None  # e.g., "Read agent_detail.py"


def parse_thinking_blocks(jsonl_path: Path) -> list[ThinkingBlock]:
    """Parse thinking blocks from a Claude Code JSONL transcript.

    Returns blocks in newest-first order.
    """
    if not jsonl_path.exists():
        return []
    lines = _read_jsonl_lines(jsonl_path)
    events = _parse_events(lines)
    return _extract_thinking_blocks(events)


def parse_thinking_blocks_multi(paths: list[Path]) -> list[ThinkingBlock]:
    """Parse thinking blocks from multiple JSONL transcripts.

    Reads lines from all paths (oldest-first order expected), merges
    them, and extracts thinking blocks.  Returns blocks in newest-first
    order, with indices numbered sequentially across all files.
    """
    all_lines: list[str] = []
    for p in paths:
        if p.exists():
            all_lines.extend(_read_jsonl_lines(p))
    if not all_lines:
        return []
    events = _parse_events(all_lines)
    return _extract_thinking_blocks(events)


def _read_jsonl_lines(path: Path) -> list[str]:
    """Read JSONL lines from a file.

    For large files (>500KB), seeks to tail and discards the first
    partial line.
    """
    file_size = path.stat().st_size
    if file_size <= _TAIL_THRESHOLD:
        with open(path, encoding="utf-8") as f:
            return f.readlines()

    # For large files, read the last _TAIL_THRESHOLD bytes
    with open(path, "rb") as f:
        f.seek(max(0, file_size - _TAIL_THRESHOLD))
        data = f.read().decode("utf-8", errors="replace")

    lines = data.split("\n")
    # Discard first partial line (unless we started at beginning)
    if file_size > _TAIL_THRESHOLD:
        lines = lines[1:]
    return [line + "\n" for line in lines if line]


def _parse_events(lines: list[str]) -> list[dict[str, Any]]:
    """Parse JSON from each line, silently skipping invalid lines."""
    events = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _extract_thinking_blocks(events: list[dict[str, Any]]) -> list[ThinkingBlock]:
    """Extract thinking blocks from parsed events, returned newest-first."""
    blocks: list[ThinkingBlock] = []
    index = 0

    for i, event in enumerate(events):
        if event.get("type") != "assistant":
            continue
        message = event.get("message", {})
        content = message.get("content", [])
        for block in content:
            if block.get("type") != "thinking":
                continue
            text = block.get("thinking", "")
            if not text.strip():
                continue
            index += 1
            timestamp = event.get("timestamp", "")
            following = _find_following_action(events, i)
            blocks.append(
                ThinkingBlock(
                    text=text,
                    timestamp=timestamp,
                    index=index,
                    following_action=following,
                )
            )

    blocks.reverse()
    return blocks


def _find_following_action(events: list[dict[str, Any]], idx: int) -> str | None:
    """Scan forward from idx to find the next action (tool_use preferred).

    Handles the common thinking → text → tool_use chain by preferring
    tool_use when found within 5 events.
    """
    text_action: str | None = None

    for j in range(idx + 1, min(idx + 6, len(events))):
        event = events[j]
        if event.get("type") != "assistant":
            continue
        message = event.get("message", {})
        content = message.get("content", [])
        for block in content:
            if block.get("type") == "tool_use":
                return _format_tool_action(block)
            if block.get("type") == "text" and text_action is None:
                text = block.get("text", "").strip()
                if text:
                    text_action = text[:80]

    return text_action


def _format_tool_action(block: dict[str, Any]) -> str:
    """Format a tool_use block into a readable action string."""
    name = block.get("name", "Unknown")
    input_data = block.get("input", {})

    if name in ("Read", "Write", "Edit"):
        file_path = input_data.get("file_path", "")
        filename = os.path.basename(file_path) if file_path else ""
        return f"{name} {filename}" if filename else name

    if name == "Bash":
        command = input_data.get("command", "")
        first_word = command.split()[0] if command.split() else ""
        return f"Bash `{first_word}`" if first_word else "Bash"

    if name in ("Grep", "Glob"):
        pattern = input_data.get("pattern", "")
        return f"{name} /{pattern}/" if pattern else name

    if name == "Task":
        return "Task (subagent)"

    if name == "Skill":
        skill = input_data.get("skill", "")
        return f"Skill {skill}" if skill else "Skill"

    return name
