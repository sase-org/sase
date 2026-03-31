"""Tests for per-chunk timestamp recording in _subprocess helpers."""

import io
import json

from sase.llm_provider._subprocess import (
    _process_codex_json_line,
    _process_json_line,
)


def _read_timestamps(ts_file: io.StringIO) -> list[dict[str, object]]:
    """Read all JSONL entries from a StringIO timestamps file."""
    ts_file.seek(0)
    return [json.loads(line) for line in ts_file if line.strip()]


# ── Gemini (stream_process_output) ──────────────────────────────────────
# stream_process_output drives a real subprocess with select(), so we test
# the paragraph-boundary logic indirectly by simulating the write pattern:
# write lines to a live_reply StringIO, tracking prev_line_blank exactly
# as stream_process_output does.


def _simulate_gemini_stream(lines: list[str]) -> list[dict[str, object]]:
    """Simulate the Gemini timestamp logic from stream_process_output."""
    live_reply = io.StringIO()
    ts_file = io.StringIO()
    prev_line_blank = True

    for line in lines:
        if prev_line_blank and line.strip():
            entry = {
                "byte_offset": live_reply.tell(),
                "timestamp": "T",
            }
            ts_file.write(json.dumps(entry) + "\n")
        prev_line_blank = not line.strip()
        live_reply.write(line)

    return _read_timestamps(ts_file)


def test_gemini_paragraph_boundary_timestamps() -> None:
    """Timestamps are recorded at each paragraph boundary (blank-line separated)."""
    lines = [
        "First paragraph line 1\n",
        "First paragraph line 2\n",
        "\n",
        "Second paragraph line 1\n",
        "\n",
        "\n",
        "Third paragraph line 1\n",
    ]
    ts = _simulate_gemini_stream(lines)
    assert len(ts) == 3
    # First paragraph starts at byte 0
    assert ts[0]["byte_offset"] == 0
    # Second paragraph starts after first paragraph + blank line
    assert ts[1]["byte_offset"] > 0
    # Third paragraph starts after second paragraph + blank lines
    assert ts[2]["byte_offset"] > ts[1]["byte_offset"]


def test_gemini_no_timestamps_for_blank_only() -> None:
    """No timestamps recorded when all lines are blank."""
    ts = _simulate_gemini_stream(["\n", "\n", "\n"])
    assert len(ts) == 0


def test_gemini_single_paragraph() -> None:
    """A single paragraph with no blank lines gets exactly one timestamp."""
    lines = ["line 1\n", "line 2\n", "line 3\n"]
    ts = _simulate_gemini_stream(lines)
    assert len(ts) == 1
    assert ts[0]["byte_offset"] == 0


# ── Claude (_process_json_line) ─────────────────────────────────────────


def test_claude_timestamp_per_text_block() -> None:
    """Each text content block within an assistant event gets its own timestamp."""
    live_reply = io.StringIO()
    ts_file = io.StringIO()
    texts: list[str] = []

    event = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "Block one"},
                {"type": "text", "text": "Block two"},
                {"type": "text", "text": "Block three"},
            ]
        },
    }
    _process_json_line(
        json.dumps(event),
        texts,
        suppress_output=True,
        live_reply_file=live_reply,
        timestamps_file=ts_file,
    )
    ts = _read_timestamps(ts_file)
    assert len(ts) == 3
    assert len(texts) == 3
    # Each timestamp should have an increasing byte_offset
    assert ts[0]["byte_offset"] < ts[1]["byte_offset"] < ts[2]["byte_offset"]


def test_claude_single_text_block() -> None:
    """A single text block gets exactly one timestamp."""
    live_reply = io.StringIO()
    ts_file = io.StringIO()
    texts: list[str] = []

    event = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "Only block"}]},
    }
    _process_json_line(
        json.dumps(event),
        texts,
        suppress_output=True,
        live_reply_file=live_reply,
        timestamps_file=ts_file,
    )
    ts = _read_timestamps(ts_file)
    assert len(ts) == 1


def test_claude_non_text_blocks_ignored() -> None:
    """Non-text blocks (tool_use etc.) don't produce timestamps."""
    live_reply = io.StringIO()
    ts_file = io.StringIO()
    texts: list[str] = []

    event = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "id": "x", "name": "foo", "input": {}},
            ]
        },
    }
    _process_json_line(
        json.dumps(event),
        texts,
        suppress_output=True,
        live_reply_file=live_reply,
        timestamps_file=ts_file,
    )
    ts = _read_timestamps(ts_file)
    assert len(ts) == 0
    assert len(texts) == 0


# ── Codex (_process_codex_json_line) ────────────────────────────────────


def test_codex_timestamp_per_agent_message() -> None:
    """Each agent_message gets its own timestamp (already correct behavior)."""
    live_reply = io.StringIO()
    ts_file = io.StringIO()
    texts: list[str] = []

    for i in range(3):
        event = {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": f"Message {i}"},
        }
        _process_codex_json_line(
            json.dumps(event),
            texts,
            suppress_output=True,
            live_reply_file=live_reply,
            timestamps_file=ts_file,
        )

    ts = _read_timestamps(ts_file)
    assert len(ts) == 3
    assert len(texts) == 3


def test_codex_no_timestamp_for_reasoning() -> None:
    """Reasoning events don't produce reply timestamps."""
    live_reply = io.StringIO()
    ts_file = io.StringIO()
    texts: list[str] = []

    event = {
        "type": "item.completed",
        "item": {
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": "thinking..."}],
        },
    }
    _process_codex_json_line(
        json.dumps(event),
        texts,
        suppress_output=True,
        live_reply_file=live_reply,
        timestamps_file=ts_file,
    )
    ts = _read_timestamps(ts_file)
    assert len(ts) == 0
    assert len(texts) == 0
