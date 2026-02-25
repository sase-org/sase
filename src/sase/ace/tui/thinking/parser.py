"""JSONL transcript parser for extracting Claude thinking blocks."""

import collections
import json
import os
from dataclasses import dataclass
from pathlib import Path
from datetime import UTC, datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent

# Files larger than this use tail-seeking optimization
_TAIL_THRESHOLD = 500 * 1024  # 500 KB


@dataclass
class ThinkingBlock:
    """A single thinking block extracted from a conversation transcript."""

    text: str
    timestamp: str
    index: int  # 1-based position (chronological)
    following_action: str | None  # e.g., "Read agent_detail.py"


_GEMINI_LOG_FILENAME = "gemini_api_proxy.par.INFO"


def _resolve_gemini_log_path() -> Path:
    """Resolve the path to the Gemini API proxy log file.

    Checks env vars in order: SASE_GEMINI_CLI_TMP → TMP → falls back to /tmp.
    """
    tmp_dir = os.environ.get("SASE_GEMINI_CLI_TMP") or os.environ.get("TMP") or "/tmp"
    return Path(tmp_dir) / _GEMINI_LOG_FILENAME


def read_gemini_log(agent: "Agent | None" = None) -> list[ThinkingBlock] | None:
    """Parse thinking blocks from the Gemini API proxy log.

    Returns:
        None if the log file doesn't exist, [] if the file is empty or has no thoughts,
        or a list of ThinkingBlocks in newest-first order.
    """
    log_path = _resolve_gemini_log_path()
    if not log_path.exists():
        return None

    # For large files (>500KB), seek to tail
    file_size = log_path.stat().st_size
    threshold = 500 * 1024
    if file_size <= threshold:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    else:
        with open(log_path, "rb") as f:
            f.seek(max(0, file_size - threshold))
            data = f.read().decode("utf-8", errors="replace")
        lines = data.split("\n")
        lines = lines[1:]  # discard partial first line
        lines = [line + "\n" for line in lines if line]

    if not lines:
        return []

    return _extract_gemini_thoughts(lines, agent)


def _extract_gemini_thoughts(
    lines: list[str], agent: "Agent | None"
) -> list[ThinkingBlock]:
    import ast
    import re

    events = []
    # 1. Parse log lines into events with timestamp
    for line in lines:
        if "Sending partial reply: b'" not in line:
            continue

        match = re.match(r"^I(\d{2})(\d{2})\s+(\d{2}:\d{2}:\d{2}\.\d+)", line)
        if match:
            month, day, time_str = match.groups()
            year = datetime.now().year
            ts_str = f"{year}-{month}-{day}T{time_str}Z"
        else:
            ts_str = ""

        start_idx = line.find("Sending partial reply: b'") + len(
            "Sending partial reply: "
        )
        byte_repr = line[start_idx:].strip()
        try:
            b_val = ast.literal_eval(byte_repr)
            json_str = b_val.decode("utf-8")
            data = json.loads(json_str)

            # Filter by agent start time if applicable
            if agent and agent.start_time and ts_str:
                # Naive ISO 8601 parsing; ts_str is YYYY-MM-DDTHH:MM:SS.mmmmmmZ
                # It's in UTC. agent.start_time is likely local time.
                # Actually, easier to let it parse all and filter later, or just string compare if both are UTC.
                pass

            events.append({"timestamp": ts_str, "data": data})
        except Exception:
            pass

    blocks: list[ThinkingBlock] = []
    index = 0
    # 2. Extract thoughts and following actions
    for i, event in enumerate(events):
        data = event["data"]
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if part.get("thought") is True and "text" in part:
                    text = part["text"].strip()
                    if not text:
                        continue

                    ts_str = event["timestamp"]
                    if agent and agent.start_time and ts_str:
                        try:
                            # ts_str ends with Z, replace with +00:00
                            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            # agent.start_time might be naive or aware
                            ast_local = agent.start_time
                            if ast_local.tzinfo is None:
                                ast_local = (
                                    ast_local.astimezone()
                                )  # convert local naive to aware

                            if dt < ast_local:
                                continue
                        except Exception:
                            pass

                    index += 1
                    following = _find_gemini_following_action(events, i)
                    blocks.append(
                        ThinkingBlock(
                            text=text,
                            timestamp=ts_str,
                            index=index,
                            following_action=following,
                        )
                    )

    # newest-first order
    blocks.reverse()

    # Adjust index for newest-first order so it stays 1..N chronological
    for i, block in enumerate(reversed(blocks)):
        block.index = i + 1

    return blocks


def _find_gemini_following_action(events: list[dict[str, Any]], idx: int) -> str | None:
    text_action = None
    for j in range(idx + 1, min(idx + 10, len(events))):
        data = events[j]["data"]
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if "functionCall" in part:
                    func = part["functionCall"]
                    name = func.get("name", "Unknown")
                    input_data = func.get("args", {})

                    if name in ("default_api:run_shell_command", "run_shell_command"):
                        command = input_data.get("command", "")
                        first_word = command.split()[0] if command.split() else ""
                        return f"Bash `{first_word}`" if first_word else "Bash"
                    elif name in ("default_api:read_file", "read_file"):
                        file_path = input_data.get("file_path", "")
                        filename = os.path.basename(file_path) if file_path else ""
                        return f"Read {filename}" if filename else "Read"
                    elif name in (
                        "default_api:replace",
                        "replace",
                        "default_api:write_file",
                        "write_file",
                    ):
                        file_path = input_data.get("file_path", "")
                        filename = os.path.basename(file_path) if file_path else ""
                        return f"Edit {filename}" if filename else "Edit"
                    elif name in ("default_api:web_fetch", "web_fetch"):
                        return "Web Fetch"
                    elif name in (
                        "default_api:codebase_investigator",
                        "codebase_investigator",
                    ):
                        return "Task (subagent)"

                    # Remove "default_api:" prefix if present
                    if name.startswith("default_api:"):
                        name = name.split(":", 1)[1]
                    return name

                if (
                    "text" in part
                    and part.get("thought") is not True
                    and text_action is None
                ):
                    text = part["text"].strip()
                    if text:
                        text_action = text[:80]

    return text_action


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
