"""JSONL transcript parser for extracting Claude thinking blocks."""

import ast
import collections
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.sase_utils import EASTERN_TZ

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

# Regex for parsing YYYYMMDD-HHMMSS timestamp from rotated log filenames
_GEMINI_FILE_TS_RE = re.compile(r"\.(\d{8}-\d{6})\.\d+$")


def _resolve_gemini_tmp_dir() -> Path:
    """Resolve the tmp directory for Gemini API proxy logs.

    Checks env vars in order: SASE_GEMINI_CLI_TMP → TMP → falls back to /tmp.
    """
    tmp_dir = os.environ.get("SASE_GEMINI_CLI_TMP") or os.environ.get("TMP") or "/tmp"
    return Path(tmp_dir)


def _resolve_gemini_log_path() -> Path:
    """Resolve the path to the Gemini API proxy log file."""
    return _resolve_gemini_tmp_dir() / _GEMINI_LOG_FILENAME


def _parse_gemini_log_timestamp(filename: str) -> datetime | None:
    """Parse the YYYYMMDD-HHMMSS timestamp from a rotated Gemini log filename.

    Returns a timezone-aware datetime in Eastern time, or None if unparseable.
    """
    m = _GEMINI_FILE_TS_RE.search(filename)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d-%H%M%S").replace(tzinfo=EASTERN_TZ)
    except ValueError:
        return None


def _find_gemini_log_files(tmp_dir: Path, since: datetime) -> list[Path]:
    """Find rotated Gemini log files with timestamps >= *since*.

    Returns paths sorted oldest-first. The current symlink is appended if its
    resolved target isn't already in the list.
    """
    timestamped: list[tuple[datetime, Path]] = []
    for p in tmp_dir.glob("gemini_api_proxy.par.*.log.INFO.*"):
        ts = _parse_gemini_log_timestamp(p.name)
        if ts is not None and ts >= since:
            timestamped.append((ts, p))

    # Sort oldest-first
    timestamped.sort(key=lambda t: t[0])
    result = [p for _, p in timestamped]

    # Also include the current symlink if its target isn't already listed
    symlink = tmp_dir / _GEMINI_LOG_FILENAME
    if symlink.exists():
        try:
            resolved = symlink.resolve()
        except OSError:
            resolved = None
        resolved_set = {p.resolve() for p in result}
        if resolved is None or resolved not in resolved_set:
            result.append(symlink)

    return result


def read_gemini_log(
    max_lines: int = 500,
    since: datetime | None = None,
) -> list[ThinkingBlock] | None:
    """Read and parse Gemini API proxy log for thinking blocks.

    When *since* is provided, reads all rotated log files whose filename
    timestamp is >= *since* (oldest-first), merging their lines before
    extracting thoughts.  When *since* is None, only the current symlink
    is read (original behaviour).

    Returns:
        None if the log file doesn't exist, [] if no thoughts found,
        or a list of ThinkingBlocks with individual thoughts (newest-first).
    """
    if since is not None:
        tmp_dir = _resolve_gemini_tmp_dir()
        log_files = _find_gemini_log_files(tmp_dir, since)
        if not log_files:
            # Fall back: try symlink alone (might have no timestamp in name)
            symlink = tmp_dir / _GEMINI_LOG_FILENAME
            if not symlink.exists():
                return None
            log_files = [symlink]

        all_lines: list[str] = []
        for lf in log_files:
            with open(lf, encoding="utf-8", errors="replace") as f:
                all_lines.extend(collections.deque(f, maxlen=max_lines))

        if not all_lines:
            return []
        return _extract_gemini_thoughts(all_lines)

    # Original single-file behaviour
    log_path = _resolve_gemini_log_path()
    if not log_path.exists():
        return None

    with open(log_path, encoding="utf-8", errors="replace") as f:
        lines = list(collections.deque(f, maxlen=max_lines))

    if not lines:
        return []

    return _extract_gemini_thoughts(lines)


# Regex for Gemini API proxy log line prefix: I<MMDD> HH:MM:SS.micros
_GEMINI_LOG_PREFIX = re.compile(r"^I(\d{2})(\d{2})\s+(\d{2}:\d{2}:\d{2})\.\d+")


def _extract_gemini_thoughts(
    lines: list[str],
) -> list[ThinkingBlock]:
    """Extract individual thinking blocks from Gemini API proxy log lines.

    Parses 'Sending partial reply' lines, decodes the byte literal to JSON,
    and collects parts where ``thought`` is True.
    """
    marker = "Sending partial reply: "

    # Build (timestamp_iso, parsed_json) event list
    events: list[tuple[str, dict[str, Any]]] = []

    for line in lines:
        pos = line.find(marker)
        if pos == -1:
            continue

        # Extract timestamp from log prefix
        m = _GEMINI_LOG_PREFIX.match(line)
        if not m:
            continue
        month, day, time_str = m.group(1), m.group(2), m.group(3)
        year = datetime.now(tz=EASTERN_TZ).year
        h, mn, s = (int(x) for x in time_str.split(":"))
        dt_obj = datetime(year, int(month), int(day), h, mn, s, tzinfo=EASTERN_TZ)
        timestamp = dt_obj.isoformat()

        # Decode byte literal → bytes → JSON
        byte_literal = line[pos + len(marker) :].rstrip()
        try:
            raw = ast.literal_eval(byte_literal)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data = json.loads(raw)
        except (ValueError, SyntaxError, json.JSONDecodeError):
            continue

        events.append((timestamp, data))

    # Walk events, pull out thought parts
    blocks: list[ThinkingBlock] = []
    index = 0

    for i, (timestamp, data) in enumerate(events):
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if part.get("thought") is not True:
                    continue
                text = part.get("text", "")
                if not text.strip():
                    continue
                index += 1
                following = _find_gemini_following_action(events, i)
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


def _find_gemini_following_action(
    events: list[tuple[str, dict[str, Any]]], idx: int
) -> str | None:
    """Scan forward from *idx* for the next Gemini action (functionCall preferred)."""
    for j in range(idx + 1, min(idx + 6, len(events))):
        _, data = events[j]
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if "functionCall" in part:
                    return _format_gemini_function_call(part["functionCall"])
                # Non-thought text as fallback
                if "text" in part and not part.get("thought"):
                    text = part["text"].strip()
                    if text:
                        return text[:80]
    return None


def _format_gemini_function_call(func_call: dict[str, Any]) -> str:
    """Format a Gemini functionCall into a readable action string."""
    name = func_call.get("name", "")
    args = func_call.get("args", {})

    # Strip default_api: prefix
    clean = name.removeprefix("default_api:")

    if clean in ("run_shell_command",):
        cmd = args.get("command", "")
        first_word = cmd.split()[0] if cmd.split() else ""
        return f"Bash `{first_word}`" if first_word else "Bash"

    if clean == "read_file":
        fp = args.get("file_path", "") or args.get("path", "")
        base = os.path.basename(fp) if fp else ""
        return f"Read {base}" if base else "Read"

    if clean in ("replace", "write_file"):
        fp = args.get("file_path", "") or args.get("path", "")
        base = os.path.basename(fp) if fp else ""
        return f"Edit {base}" if base else "Edit"

    if clean == "web_fetch":
        return "Web Fetch"

    if clean == "codebase_investigator":
        return "Task (subagent)"

    return clean


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
