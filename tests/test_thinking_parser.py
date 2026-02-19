"""Tests for sase.ace.tui.thinking.parser."""

import json
from pathlib import Path
from typing import Any

from sase.ace.tui.thinking.parser import (
    ThinkingBlock,
    _format_tool_action,
    _read_jsonl_lines,
    parse_thinking_blocks,
)


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


def test_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    assert parse_thinking_blocks(path) == []


def test_no_thinking_blocks(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path, [_make_text_event("hello")])
    assert parse_thinking_blocks(path) == []


def test_single_thinking_block(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path,
        [_make_thinking_event("I should read the file", "2026-01-15T10:00:00Z")],
    )
    blocks = parse_thinking_blocks(path)
    assert len(blocks) == 1
    assert blocks[0].text == "I should read the file"
    assert blocks[0].timestamp == "2026-01-15T10:00:00Z"
    assert blocks[0].index == 1
    assert blocks[0].following_action is None


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


def test_thinking_followed_by_tool_use(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path,
        [
            _make_thinking_event("Let me read that"),
            _make_tool_use_event("Read", {"file_path": "/src/foo/bar.py"}),
        ],
    )
    blocks = parse_thinking_blocks(path)
    assert len(blocks) == 1
    assert blocks[0].following_action == "Read bar.py"


def test_thinking_text_tool_use_chain(tmp_path: Path) -> None:
    """Thinking → text → tool_use chain prefers tool_use."""
    path = _write_jsonl(
        tmp_path,
        [
            _make_thinking_event("Analyzing the code"),
            _make_text_event("Let me check the file."),
            _make_tool_use_event("Grep", {"pattern": "def main"}),
        ],
    )
    blocks = parse_thinking_blocks(path)
    assert len(blocks) == 1
    assert blocks[0].following_action == "Grep /def main/"


def test_thinking_at_eof_none_action(tmp_path: Path) -> None:
    """Thinking at end of file has no following action."""
    path = _write_jsonl(
        tmp_path,
        [
            _make_text_event("some text"),
            _make_thinking_event("final thought"),
        ],
    )
    blocks = parse_thinking_blocks(path)
    assert len(blocks) == 1
    assert blocks[0].following_action is None


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


def test_one_based_indexing(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path,
        [
            _make_thinking_event("first"),
            _make_thinking_event("second"),
        ],
    )
    blocks = parse_thinking_blocks(path)
    # Reversed order, but index reflects chronological position
    assert blocks[0].index == 2  # newest first, but index=2 (chronological)
    assert blocks[1].index == 1


def test_timestamp_preserved(tmp_path: Path) -> None:
    ts = "2026-02-19T14:30:45.123Z"
    path = _write_jsonl(tmp_path, [_make_thinking_event("thought", ts)])
    blocks = parse_thinking_blocks(path)
    assert blocks[0].timestamp == ts


def test_nonexistent_file() -> None:
    assert parse_thinking_blocks(Path("/nonexistent/path.jsonl")) == []


# --- _format_tool_action ---


def test_format_read() -> None:
    block = {"name": "Read", "input": {"file_path": "/home/user/src/agent_detail.py"}}
    assert _format_tool_action(block) == "Read agent_detail.py"


def test_format_write() -> None:
    block = {"name": "Write", "input": {"file_path": "/tmp/output.txt"}}
    assert _format_tool_action(block) == "Write output.txt"


def test_format_edit() -> None:
    block = {"name": "Edit", "input": {"file_path": "/src/main.py"}}
    assert _format_tool_action(block) == "Edit main.py"


def test_format_bash() -> None:
    block = {"name": "Bash", "input": {"command": "just lint"}}
    assert _format_tool_action(block) == "Bash `just`"


def test_format_bash_empty_command() -> None:
    block = {"name": "Bash", "input": {"command": ""}}
    assert _format_tool_action(block) == "Bash"


def test_format_grep() -> None:
    block = {"name": "Grep", "input": {"pattern": "def main"}}
    assert _format_tool_action(block) == "Grep /def main/"


def test_format_glob() -> None:
    block = {"name": "Glob", "input": {"pattern": "**/*.py"}}
    assert _format_tool_action(block) == "Glob /**/*.py/"


def test_format_task() -> None:
    block = {"name": "Task", "input": {"prompt": "do something"}}
    assert _format_tool_action(block) == "Task (subagent)"


def test_format_skill() -> None:
    block = {"name": "Skill", "input": {"skill": "commit"}}
    assert _format_tool_action(block) == "Skill commit"


def test_format_unknown_tool() -> None:
    block = {"name": "WebSearch", "input": {}}
    assert _format_tool_action(block) == "WebSearch"


def test_format_read_no_file_path() -> None:
    block = {"name": "Read", "input": {}}
    assert _format_tool_action(block) == "Read"


# --- _read_jsonl_lines ---


def test_small_file_reads_all(tmp_path: Path) -> None:
    path = tmp_path / "small.jsonl"
    lines_data = [json.dumps({"i": i}) for i in range(10)]
    path.write_text("\n".join(lines_data) + "\n")
    lines = _read_jsonl_lines(path)
    assert len(lines) == 10


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
