"""Tests for sase.ace.tui.thinking.parser."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.ace.tui.thinking.parser import (
    _format_gemini_function_call,
    _format_tool_action,
    _parse_gemini_log_timestamp,
    _read_jsonl_lines,
    parse_thinking_blocks,
    read_codex_thinking,
    read_gemini_log,
)
from sase.ace.tui.widgets.thinking_panel import _format_timestamp
from sase.core.time import get_timezone


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


# --- _resolve_gemini_log_path ---


# --- read_gemini_log ---


def _gemini_log_line(
    text: str,
    thought: bool = True,
    mmdd: str = "0225",
    time: str = "16:04:04",
    micros: str = "046658",
    pid: str = "3485334",
    function_call: dict[str, Any] | None = None,
) -> str:
    """Build a realistic Gemini API proxy log line."""
    if function_call is not None:
        parts = [{"functionCall": function_call}]
    else:
        part: dict[str, Any] = {"text": text}
        if thought:
            part["thought"] = True
        parts = [part]
    payload = json.dumps(
        {"candidates": [{"content": {"parts": parts, "role": "model"}}]}
    )
    byte_repr = repr(payload.encode())
    return (
        f"I{mmdd} {time}.{micros} {pid} "
        f"gemini_api_proxy_lib.py:529] Sending partial reply: {byte_repr}\n"
    )


def test_read_gemini_log_file_exists(tmp_path: Path, monkeypatch: Any) -> None:
    """Parses a thought from realistic Gemini log format."""
    log_file = tmp_path / "gemini_api_proxy.par.INFO"
    log_file.write_text(_gemini_log_line("Let me think about this", thought=True))
    monkeypatch.setenv("SASE_GEMINI_CLI_TMP", str(tmp_path))
    result = read_gemini_log()
    assert result is not None
    assert len(result) == 1
    assert result[0].text == "Let me think about this"
    assert result[0].index == 1


def test_read_gemini_log_timestamp_is_eastern(tmp_path: Path, monkeypatch: Any) -> None:
    """Gemini log timestamps are tagged as Eastern, not UTC."""
    log_file = tmp_path / "gemini_api_proxy.par.INFO"
    log_file.write_text(_gemini_log_line("thought", time="14:30:00"))
    monkeypatch.setenv("SASE_GEMINI_CLI_TMP", str(tmp_path))
    result = read_gemini_log()
    assert result is not None
    ts = result[0].timestamp
    # Timestamp should preserve 14:30 as Eastern, not mark it as UTC
    assert "14:30:00" in ts
    assert ts.endswith("-05:00") or ts.endswith("-04:00")  # EST or EDT
    # Formatting via _format_timestamp should keep the same hour
    assert _format_timestamp(ts) == "14:30:00"


def test_read_gemini_log_multiple_thoughts_newest_first(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Multiple thoughts are returned newest-first."""
    log_file = tmp_path / "gemini_api_proxy.par.INFO"
    log_file.write_text(
        _gemini_log_line("first thought", time="10:00:00")
        + _gemini_log_line("second thought", time="10:01:00")
        + _gemini_log_line("third thought", time="10:02:00")
    )
    monkeypatch.setenv("SASE_GEMINI_CLI_TMP", str(tmp_path))
    result = read_gemini_log()
    assert result is not None
    assert len(result) == 3
    assert result[0].text == "third thought"
    assert result[1].text == "second thought"
    assert result[2].text == "first thought"


def test_read_gemini_log_following_action_function_call(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Detects following action from a functionCall in subsequent events."""
    log_file = tmp_path / "gemini_api_proxy.par.INFO"
    log_file.write_text(
        _gemini_log_line("thinking about file", time="10:00:00")
        + _gemini_log_line(
            "",
            thought=False,
            time="10:00:01",
            function_call={
                "name": "default_api:read_file",
                "args": {"file_path": "/tmp/foo/bar.py"},
            },
        )
    )
    monkeypatch.setenv("SASE_GEMINI_CLI_TMP", str(tmp_path))
    result = read_gemini_log()
    assert result is not None
    assert len(result) == 1
    assert result[0].following_action == "Read bar.py"


def test_read_gemini_log_non_thought_excluded(tmp_path: Path, monkeypatch: Any) -> None:
    """Non-thought parts are not extracted as blocks."""
    log_file = tmp_path / "gemini_api_proxy.par.INFO"
    log_file.write_text(
        _gemini_log_line("regular text", thought=False)
        + _gemini_log_line("a real thought", thought=True)
    )
    monkeypatch.setenv("SASE_GEMINI_CLI_TMP", str(tmp_path))
    result = read_gemini_log()
    assert result is not None
    assert len(result) == 1
    assert result[0].text == "a real thought"


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


# --- _format_gemini_function_call ---


def test_format_gemini_shell_command() -> None:
    fc = {"name": "default_api:run_shell_command", "args": {"command": "ls -la"}}
    assert _format_gemini_function_call(fc) == "Bash `ls`"


def test_format_gemini_read_file() -> None:
    fc = {"name": "default_api:read_file", "args": {"file_path": "/a/b/c.py"}}
    assert _format_gemini_function_call(fc) == "Read c.py"


def test_format_gemini_write_file() -> None:
    fc = {"name": "default_api:write_file", "args": {"file_path": "/x/y.txt"}}
    assert _format_gemini_function_call(fc) == "Edit y.txt"


def test_format_gemini_unknown_strips_prefix() -> None:
    fc = {"name": "default_api:some_tool", "args": {}}
    assert _format_gemini_function_call(fc) == "some_tool"


# --- _parse_gemini_log_timestamp ---


def test_parse_gemini_log_timestamp() -> None:
    filename = "gemini_api_proxy.par.host.user.log.INFO.20260225-140000.12345"
    result = _parse_gemini_log_timestamp(filename)
    assert result is not None
    assert result.year == 2026
    assert result.month == 2
    assert result.day == 25
    assert result.hour == 14
    assert result.minute == 0
    assert result.tzinfo == get_timezone()


def test_parse_gemini_log_timestamp_invalid() -> None:
    assert _parse_gemini_log_timestamp("not-a-log-file.txt") is None
    assert _parse_gemini_log_timestamp("gemini_api_proxy.par.INFO") is None


# --- read_gemini_log with since ---


def test_read_gemini_log_multi_files_with_since(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Two timestamped files — both read and merged, newest-first."""
    monkeypatch.setenv("SASE_GEMINI_CLI_TMP", str(tmp_path))

    # Older rotated file
    old_file = tmp_path / "gemini_api_proxy.par.host.user.log.INFO.20260225-100000.111"
    old_file.write_text(_gemini_log_line("old thought", time="10:00:00"))

    # Newer rotated file
    new_file = tmp_path / "gemini_api_proxy.par.host.user.log.INFO.20260225-110000.222"
    new_file.write_text(_gemini_log_line("new thought", time="11:00:00"))

    since = datetime(2026, 2, 25, 9, 0, 0, tzinfo=get_timezone())
    result = read_gemini_log(since=since)
    assert result is not None
    assert len(result) == 2
    # Newest-first
    assert result[0].text == "new thought"
    assert result[1].text == "old thought"


def test_read_gemini_log_accepts_naive_since(tmp_path: Path, monkeypatch: Any) -> None:
    """Naive agent timestamps are treated as configured-local time."""
    monkeypatch.setenv("SASE_GEMINI_CLI_TMP", str(tmp_path))

    log_file = tmp_path / "gemini_api_proxy.par.host.user.log.INFO.20260225-100000.111"
    log_file.write_text(_gemini_log_line("local naive thought", time="10:00:00"))

    result = read_gemini_log(since=datetime(2026, 2, 25, 9, 0, 0))

    assert result is not None
    assert len(result) == 1
    assert result[0].text == "local naive thought"


def test_read_gemini_log_since_filters_old_files(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """File before *since* is excluded."""
    monkeypatch.setenv("SASE_GEMINI_CLI_TMP", str(tmp_path))

    # File timestamped before since
    old_file = tmp_path / "gemini_api_proxy.par.host.user.log.INFO.20260225-080000.111"
    old_file.write_text(_gemini_log_line("too old", time="08:00:00"))

    # File timestamped after since
    new_file = tmp_path / "gemini_api_proxy.par.host.user.log.INFO.20260225-120000.222"
    new_file.write_text(_gemini_log_line("recent", time="12:00:00"))

    since = datetime(2026, 2, 25, 10, 0, 0, tzinfo=get_timezone())
    result = read_gemini_log(since=since)
    assert result is not None
    assert len(result) == 1
    assert result[0].text == "recent"


def test_read_gemini_log_since_includes_symlink(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Symlink is included when its target is not in timestamped files."""
    monkeypatch.setenv("SASE_GEMINI_CLI_TMP", str(tmp_path))

    # Create a symlink pointing to a file NOT matching the glob pattern
    actual_log = tmp_path / "current.log"
    actual_log.write_text(_gemini_log_line("symlink thought", time="15:00:00"))
    symlink = tmp_path / "gemini_api_proxy.par.INFO"
    symlink.symlink_to(actual_log)

    since = datetime(2026, 2, 25, 9, 0, 0, tzinfo=get_timezone())
    result = read_gemini_log(since=since)
    assert result is not None
    assert len(result) == 1
    assert result[0].text == "symlink thought"


def test_read_gemini_log_since_no_files_returns_none(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """No files or symlink → None."""
    monkeypatch.setenv("SASE_GEMINI_CLI_TMP", str(tmp_path))
    since = datetime(2026, 2, 25, 9, 0, 0, tzinfo=get_timezone())
    result = read_gemini_log(since=since)
    assert result is None


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
