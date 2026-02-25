"""Tests for sase.ace.tui.thinking.parser."""

import json
from pathlib import Path
from typing import Any

from sase.ace.tui.thinking.parser import (
    _format_tool_action,
    _read_jsonl_lines,
    parse_thinking_blocks,
    read_gemini_log,
)
from sase.ace.tui.widgets.thinking_panel import _format_timestamp


# --- helpers ---


def _make_thinking_event(text: str, ts: str = "2026-01-15T10:00:00Z") -> dict[str, Any]:
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "content": [{"type": "thinking", "thinking": text}],
            "stop_reason": None,
        },
    }


def _make_tool_use_event(
    name: str,
    input_data: dict[str, Any] | None = None,
    ts: str = "2026-01-15T10:00:01Z",
) -> dict[str, Any]:
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "name": name,
                    "input": input_data or {},
                }
            ],
            "stop_reason": None,
        },
    }


def _make_text_event(text: str, ts: str = "2026-01-15T10:00:01Z") -> dict[str, Any]:
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "content": [{"type": "text", "text": text}],
            "stop_reason": None,
        },
    }


def _write_jsonl(tmp_path: Path, events: list[dict[str, Any]]) -> Path:
    path = tmp_path / "session.jsonl"
    with open(path, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    return path


# --- parse_thinking_blocks ---


def test_multiple_blocks_newest_first(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path,
        [
            _make_thinking_event("first thought", "2026-01-15T10:00:00Z"),
            _make_thinking_event("second thought", "2026-01-15T10:01:00Z"),
            _make_thinking_event("third thought", "2026-01-15T10:02:00Z"),
        ],
    )
    blocks = parse_thinking_blocks(path)
    assert len(blocks) == 3
    # Newest first
    assert blocks[0].text == "third thought"
    assert blocks[1].text == "second thought"
    assert blocks[2].text == "first thought"


def test_empty_thinking_text_skipped(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path,
        [
            _make_thinking_event(""),
            _make_thinking_event("   "),
            _make_thinking_event("real thought"),
        ],
    )
    blocks = parse_thinking_blocks(path)
    assert len(blocks) == 1
    assert blocks[0].text == "real thought"


def test_malformed_json_skipped(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    with open(path, "w") as f:
        f.write("not json\n")
        f.write(json.dumps(_make_thinking_event("valid thought")) + "\n")
        f.write("{truncated\n")
    blocks = parse_thinking_blocks(path)
    assert len(blocks) == 1
    assert blocks[0].text == "valid thought"


def test_nonexistent_file(tmp_path: Path) -> None:
    assert parse_thinking_blocks(tmp_path / "nonexistent.jsonl") == []


# --- _format_tool_action ---


def test_format_bash_empty_command() -> None:
    block = {"name": "Bash", "input": {"command": ""}}
    assert _format_tool_action(block) == "Bash"


def test_format_grep() -> None:
    block = {"name": "Grep", "input": {"pattern": "def main"}}
    assert _format_tool_action(block) == "Grep /def main/"


def test_format_skill() -> None:
    block = {"name": "Skill", "input": {"skill": "commit"}}
    assert _format_tool_action(block) == "Skill commit"


# --- _read_jsonl_lines ---


def test_large_file_reads_tail(tmp_path: Path) -> None:
    """Files >500KB only read the tail portion."""
    path = tmp_path / "large.jsonl"
    # Write enough data to exceed 500KB threshold
    with open(path, "w") as f:
        for i in range(10000):
            f.write(json.dumps({"i": i, "padding": "x" * 100}) + "\n")
    assert path.stat().st_size > 500 * 1024

    lines = _read_jsonl_lines(path)
    # Should have fewer lines than the total
    assert len(lines) < 10000
    assert len(lines) > 0
    # Last line should be parseable
    last = json.loads(lines[-1])
    assert last["i"] == 9999


# --- _format_timestamp ---


def test_format_timestamp_invalid_input() -> None:
    """Invalid input returns fallback string."""
    assert _format_timestamp("not-a-timestamp") == "??:??:??"


# --- _resolve_gemini_log_path ---


# --- read_gemini_log ---


def test_read_gemini_log_file_exists(tmp_path: Path, monkeypatch: Any) -> None:
    """Returns parsed ThinkingBlocks from log content."""
    log_file = tmp_path / "gemini_api_proxy.par.INFO"
    
    # Mock log content matching proxy log format
    log_file.write_text(
        "I0225 14:24:44.431123 2721368 gemini_api_proxy_lib.py:529] Sending partial reply: "
        "b'{\"candidates\": [{\"content\": {\"parts\": [{\"text\": \"My thought\", \"thought\": true}], \"role\": \"model\"}}]}\\n'\n"
    )
    monkeypatch.setenv("SASE_GEMINI_CLI_TMP", str(tmp_path))
    result = read_gemini_log()
    assert result is not None
    assert len(result) == 1
    assert "My thought" == result[0].text
    assert result[0].index == 1


def test_read_gemini_log_file_missing(tmp_path: Path, monkeypatch: Any) -> None:
    """Returns None when log file doesn't exist."""
    monkeypatch.setenv("SASE_GEMINI_CLI_TMP", str(tmp_path))
    result = read_gemini_log()
    assert result is None


def test_read_gemini_log_empty_file(tmp_path: Path, monkeypatch: Any) -> None:
    """Returns [] for empty log file."""
    log_file = tmp_path / "gemini_api_proxy.par.INFO"
    log_file.write_text("")
    monkeypatch.setenv("SASE_GEMINI_CLI_TMP", str(tmp_path))
    result = read_gemini_log()
    assert result == []
