"""Tests for sase.ace.tui.thinking.parser."""

import json
from pathlib import Path
from typing import Any

from sase.ace.tui.thinking.parser import (
    _format_tool_action,
    _read_jsonl_lines,
    parse_thinking_blocks,
    read_codex_thinking,
)
from sase.ace.tui.widgets.tools_panel import _format_timestamp


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


def _make_encrypted_thinking_event(
    *,
    signature: str = "EvsBClkIDR_signature_blob",
    output_tokens: int | None = 274,
    ts: str = "2026-05-12T10:00:00Z",
) -> dict[str, Any]:
    usage: dict[str, Any] = {}
    if output_tokens is not None:
        usage["output_tokens"] = output_tokens
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "content": [{"type": "thinking", "thinking": "", "signature": signature}],
            "usage": usage,
            "stop_reason": None,
        },
    }


def test_signature_only_block_emits_placeholder(tmp_path: Path) -> None:
    """Opus 4.7 encrypts thinking; emit placeholder when signature is present."""
    path = _write_jsonl(
        tmp_path,
        [_make_encrypted_thinking_event(output_tokens=274)],
    )
    blocks = parse_thinking_blocks(path)
    assert len(blocks) == 1
    assert blocks[0].text == "[encrypted thought · ~274 output tokens]"


def test_signature_only_block_without_token_count(tmp_path: Path) -> None:
    """Falls back to bare placeholder when output_tokens is missing."""
    path = _write_jsonl(
        tmp_path,
        [_make_encrypted_thinking_event(output_tokens=None)],
    )
    blocks = parse_thinking_blocks(path)
    assert len(blocks) == 1
    assert blocks[0].text == "[encrypted thought]"


def test_empty_signature_and_empty_thinking_still_skipped(tmp_path: Path) -> None:
    """A truly empty thinking block (no signature either) is dropped."""
    path = _write_jsonl(
        tmp_path,
        [_make_encrypted_thinking_event(signature="", output_tokens=274)],
    )
    blocks = parse_thinking_blocks(path)
    assert blocks == []


def test_signature_only_block_picks_up_following_action(tmp_path: Path) -> None:
    """Placeholder blocks still get the next tool_use attached as following action."""
    path = _write_jsonl(
        tmp_path,
        [
            _make_encrypted_thinking_event(output_tokens=100),
            _make_tool_use_event("Read", {"file_path": "/x/foo.py"}),
        ],
    )
    blocks = parse_thinking_blocks(path)
    assert len(blocks) == 1
    assert blocks[0].text == "[encrypted thought · ~100 output tokens]"
    assert blocks[0].following_action == "Read foo.py"


def test_malformed_json_skipped(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    with open(path, "w") as f:
        f.write("not json\n")
        f.write(json.dumps(_make_thinking_event("valid thought")) + "\n")
        f.write("{truncated\n")
    blocks = parse_thinking_blocks(path)
    assert len(blocks) == 1
    assert blocks[0].text == "valid thought"


def test_nonexistent_file() -> None:
    assert parse_thinking_blocks(Path("/nonexistent/path.jsonl")) == []


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


# --- read_codex_thinking tests ---


def test_read_codex_thinking_returns_none_when_no_file(tmp_path: Path) -> None:
    """Returns None when codex_thinking.jsonl doesn't exist."""
    result = read_codex_thinking(str(tmp_path))
    assert result is None


def test_read_codex_thinking_returns_empty_for_empty_file(tmp_path: Path) -> None:
    """Returns [] when the file exists but has no entries."""
    (tmp_path / "codex_thinking.jsonl").write_text("")
    result = read_codex_thinking(str(tmp_path))
    assert result == []


def test_read_codex_thinking_parses_entries(tmp_path: Path) -> None:
    """Parses thinking entries and returns newest-first."""
    entries = [
        json.dumps({"text": "First thought", "timestamp": "2026-03-13T10:00:00+00:00"}),
        json.dumps(
            {"text": "Second thought", "timestamp": "2026-03-13T10:01:00+00:00"}
        ),
    ]
    (tmp_path / "codex_thinking.jsonl").write_text("\n".join(entries) + "\n")

    result = read_codex_thinking(str(tmp_path))
    assert result is not None
    assert len(result) == 2
    # Newest-first order
    assert result[0].text == "Second thought"
    assert result[0].index == 2
    assert result[1].text == "First thought"
    assert result[1].index == 1


def test_read_codex_thinking_skips_empty_text(tmp_path: Path) -> None:
    """Entries with empty text are skipped."""
    entries = [
        json.dumps({"text": "", "timestamp": "2026-03-13T10:00:00+00:00"}),
        json.dumps({"text": "Real thought", "timestamp": "2026-03-13T10:01:00+00:00"}),
    ]
    (tmp_path / "codex_thinking.jsonl").write_text("\n".join(entries) + "\n")

    result = read_codex_thinking(str(tmp_path))
    assert result is not None
    assert len(result) == 1
    assert result[0].text == "Real thought"


def test_read_codex_thinking_handles_malformed_lines(tmp_path: Path) -> None:
    """Malformed JSON lines are silently skipped."""
    content = (
        "{broken json\n"
        + json.dumps({"text": "Valid", "timestamp": "2026-03-13T10:00:00+00:00"})
        + "\n"
    )
    (tmp_path / "codex_thinking.jsonl").write_text(content)

    result = read_codex_thinking(str(tmp_path))
    assert result is not None
    assert len(result) == 1
    assert result[0].text == "Valid"


def test_read_codex_thinking_parses_following_action(tmp_path: Path) -> None:
    """following_action is read from JSONL entries when present."""
    entries = [
        json.dumps(
            {
                "text": "Thought A",
                "timestamp": "2026-03-13T10:00:00+00:00",
                "following_action": "Read config.py",
            }
        ),
        json.dumps(
            {
                "text": "Thought B",
                "timestamp": "2026-03-13T10:01:00+00:00",
            }
        ),
    ]
    (tmp_path / "codex_thinking.jsonl").write_text("\n".join(entries) + "\n")

    result = read_codex_thinking(str(tmp_path))
    assert result is not None
    assert len(result) == 2
    # Blocks are reversed (newest first)
    assert result[0].following_action is None  # Thought B (no action)
    assert result[1].following_action == "Read config.py"  # Thought A
