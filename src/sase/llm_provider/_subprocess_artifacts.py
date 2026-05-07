"""Artifact and text-output helpers for LLM subprocess streaming."""

import json
import os
import re
from datetime import UTC, datetime
from typing import IO

# Matches ANSI escape sequences: CSI, OSC, charset selection, and other
# single-character escapes. Used to clean PTY output that may contain color
# codes or cursor-movement sequences.
_ANSI_RE = re.compile(
    r"\x1b"
    r"(?:"
    r"\[[0-9;?]*[A-Za-z@]"  # CSI sequences (colors, cursor, erase, etc.)
    r"|\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC sequences
    r"|[()][0-9A-Za-z]"  # Charset selection
    r"|."  # Any other ESC + single char
    r")"
)


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences and bare carriage returns from *text*."""
    text = _ANSI_RE.sub("", text)
    # Normalize CRLF then strip bare CR (spinner overwrites, etc.)
    return text.replace("\r\n", "\n").replace("\r", "")


def open_live_reply_file() -> IO[str] | None:
    """Open the live reply file for writing if SASE_ARTIFACTS_DIR is set."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return None
    path = os.path.join(artifacts_dir, "live_reply.md")
    return open(path, "w", encoding="utf-8")


def open_live_reply_timestamps_file() -> IO[str] | None:
    """Open the live reply timestamps JSONL file if SASE_ARTIFACTS_DIR is set."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return None
    path = os.path.join(artifacts_dir, "live_reply_timestamps.jsonl")
    return open(path, "w", encoding="utf-8")


def open_codex_thinking_file() -> IO[str] | None:
    """Open the Codex thinking JSONL file if SASE_ARTIFACTS_DIR is set."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return None
    path = os.path.join(artifacts_dir, "codex_thinking.jsonl")
    return open(path, "w", encoding="utf-8")


def write_usage_artifact(usage_totals: dict[str, int]) -> None:
    """Write usage.json to the artifacts directory if SASE_ARTIFACTS_DIR is set."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return
    path = os.path.join(artifacts_dir, "usage.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(usage_totals, f, indent=2)
        f.write("\n")


def write_reply_timestamp(
    live_reply_file: IO[str],
    timestamps_file: IO[str] | None,
) -> None:
    """Write a timestamp entry at the current live-reply byte offset."""
    if timestamps_file is None:
        return
    ts_entry = {
        "byte_offset": live_reply_file.tell(),
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }
    timestamps_file.write(json.dumps(ts_entry) + "\n")
    timestamps_file.flush()


def append_stream_text(
    text: str,
    assistant_texts: list[str],
    suppress_output: bool,
    live_reply_file: IO[str] | None,
    timestamps_file: IO[str] | None,
) -> None:
    """Append extracted assistant text to memory, artifacts, and console."""
    if live_reply_file:
        write_reply_timestamp(live_reply_file, timestamps_file)
        if assistant_texts:
            live_reply_file.write("\n\n")
        live_reply_file.write(text)
        live_reply_file.flush()
    assistant_texts.append(text)
    if not suppress_output:
        print(text, flush=True)


def initial_usage_totals() -> dict[str, int]:
    """Return the common SASE token usage counter shape."""
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def int_usage(value: object) -> int:
    """Return *value* as an int usage count when possible."""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


_append_stream_text = append_stream_text
_initial_usage_totals = initial_usage_totals
_int_usage = int_usage
_open_codex_thinking_file = open_codex_thinking_file
_open_live_reply_file = open_live_reply_file
_open_live_reply_timestamps_file = open_live_reply_timestamps_file
_strip_ansi = strip_ansi
_write_reply_timestamp = write_reply_timestamp
_write_usage_artifact = write_usage_artifact
