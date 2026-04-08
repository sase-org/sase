"""Tests for token usage parsing from Claude Code stream-json events."""

import json
import os
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

from sase.llm_provider._subprocess import (
    _process_json_line,
    stream_and_parse_json_output,
)


# ---------------------------------------------------------------------------
# _process_json_line: usage extraction
# ---------------------------------------------------------------------------


def test_process_json_line_extracts_usage_from_result() -> None:
    """result events with usage dicts accumulate into usage_totals."""
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    event = {
        "type": "result",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 10,
            "cache_read_input_tokens": 20,
        },
    }
    _process_json_line(
        json.dumps(event),
        assistant_texts=[],
        suppress_output=True,
        usage_totals=usage_totals,
    )
    assert usage_totals == {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_creation_input_tokens": 10,
        "cache_read_input_tokens": 20,
    }


def test_process_json_line_accumulates_across_events() -> None:
    """Multiple result events sum into usage_totals."""
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    for _ in range(3):
        event = {
            "type": "result",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        _process_json_line(
            json.dumps(event),
            assistant_texts=[],
            suppress_output=True,
            usage_totals=usage_totals,
        )
    assert usage_totals["input_tokens"] == 30
    assert usage_totals["output_tokens"] == 15
    assert usage_totals["cache_creation_input_tokens"] == 0


def test_process_json_line_no_usage_in_result() -> None:
    """result events without usage dict don't crash."""
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    event = {"type": "result", "result": "some text"}
    _process_json_line(
        json.dumps(event),
        assistant_texts=[],
        suppress_output=True,
        usage_totals=usage_totals,
    )
    assert usage_totals["input_tokens"] == 0


def test_process_json_line_usage_totals_none_ignored() -> None:
    """When usage_totals is None, result events don't crash."""
    event = {
        "type": "result",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }
    # Should not raise
    _process_json_line(
        json.dumps(event),
        assistant_texts=[],
        suppress_output=True,
        usage_totals=None,
    )


def test_process_json_line_error_events_still_captured() -> None:
    """error_events capture still works alongside usage extraction."""
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    error_events: list[str] = []
    event = {
        "type": "result",
        "result": "done",
        "usage": {"input_tokens": 42, "output_tokens": 7},
    }
    _process_json_line(
        json.dumps(event),
        assistant_texts=[],
        suppress_output=True,
        error_events=error_events,
        usage_totals=usage_totals,
    )
    assert usage_totals["input_tokens"] == 42
    assert len(error_events) == 1
    assert "[result]" in error_events[0]


# ---------------------------------------------------------------------------
# stream_and_parse_json_output: usage in return value
# ---------------------------------------------------------------------------


def test_stream_and_parse_json_output_returns_usage() -> None:
    """stream_and_parse_json_output returns usage_totals as 4th element."""
    events = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hello"}]},
            }
        ),
        json.dumps(
            {
                "type": "result",
                "usage": {"input_tokens": 200, "output_tokens": 80},
            }
        ),
    ]
    process = MagicMock(spec=subprocess.Popen)
    process.stdout = MagicMock()
    process.stderr = MagicMock()
    process.stdout.fileno.return_value = 99
    process.stderr.fileno.return_value = 100

    # Simulate readline returning lines then empty string
    process.stdout.readline = MagicMock(side_effect=[*[e + "\n" for e in events], ""])
    process.stderr.readline = MagicMock(return_value="")
    process.poll = MagicMock(side_effect=[None, None, 0])
    process.wait = MagicMock(return_value=0)

    # After poll returns 0, remaining stdout/stderr iteration yields nothing
    process.stdout.__iter__ = MagicMock(return_value=iter([]))
    process.stderr.__iter__ = MagicMock(return_value=iter([]))

    with patch("sase.llm_provider._subprocess.os.set_blocking"):
        with patch("sase.llm_provider._subprocess.select.select") as mock_select:
            mock_select.side_effect = [
                ([process.stdout], [], []),
                ([process.stdout], [], []),
                ([process.stdout], [], []),
            ]
            text, stderr, rc, usage = stream_and_parse_json_output(
                process, suppress_output=True
            )

    assert rc == 0
    assert "hello" in text
    assert usage["input_tokens"] == 200
    assert usage["output_tokens"] == 80


# ---------------------------------------------------------------------------
# usage.json artifact writing
# ---------------------------------------------------------------------------


def test_usage_json_written_to_artifacts_dir() -> None:
    """usage.json is written to SASE_ARTIFACTS_DIR."""
    events = [
        json.dumps(
            {
                "type": "result",
                "usage": {"input_tokens": 300, "output_tokens": 120},
            }
        ),
    ]

    process = MagicMock(spec=subprocess.Popen)
    process.stdout = MagicMock()
    process.stderr = MagicMock()
    process.stdout.fileno.return_value = 99
    process.stderr.fileno.return_value = 100
    process.stdout.readline = MagicMock(side_effect=[events[0] + "\n", ""])
    process.stderr.readline = MagicMock(return_value="")
    process.poll = MagicMock(side_effect=[None, 0])
    process.wait = MagicMock(return_value=0)
    process.stdout.__iter__ = MagicMock(return_value=iter([]))
    process.stderr.__iter__ = MagicMock(return_value=iter([]))

    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": tmpdir}),
            patch("sase.llm_provider._subprocess.os.set_blocking"),
            patch("sase.llm_provider._subprocess.select.select") as mock_select,
        ):
            mock_select.side_effect = [
                ([process.stdout], [], []),
                ([process.stdout], [], []),
            ]
            stream_and_parse_json_output(process, suppress_output=True)

        usage_path = os.path.join(tmpdir, "usage.json")
        assert os.path.exists(usage_path)
        with open(usage_path) as f:
            data = json.load(f)
        assert data["input_tokens"] == 300
        assert data["output_tokens"] == 120
