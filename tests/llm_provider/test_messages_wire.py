"""Tests for the provider-neutral Anthropic Messages stream parser."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from sase.ace.tui.thinking.parser import read_codex_thinking
from sase.llm_provider._subprocess import (
    _process_json_line,
    _stream_and_parse_messages_json_output,
)


def _diagnostics(path: Path) -> list[dict[str, object]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_messages_errors_array_is_folded_into_failure_detail() -> None:
    error_events: list[str] = []
    event = {
        "type": "result",
        "subtype": "error_during_execution",
        "is_error": True,
        "errors": [
            "Couldn't set model 'definitely-not-a-model'",
            "Invalid params: unknown model id",
        ],
    }

    _process_json_line(
        json.dumps(event),
        assistant_texts=[],
        suppress_output=True,
        error_events=error_events,
    )

    assert error_events == [
        "[result] Couldn't set model 'definitely-not-a-model'\n"
        "Invalid params: unknown model id"
    ]


def test_messages_decode_diagnostics_use_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    _process_json_line('{"bad":', [], suppress_output=True, runtime="grok")

    entries = _diagnostics(tmp_path / "tool_calls_writer_errors.jsonl")
    assert entries[0]["reason"] == "grok_stdout_json_decode_error"
    assert entries[0]["line_length"] == len('{"bad":')


def test_messages_tool_call_writer_seam_receives_each_event() -> None:
    event = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "hello"}]},
    }
    seen: list[Mapping[str, object]] = []
    texts: list[str] = []

    _process_json_line(
        json.dumps(event),
        texts,
        suppress_output=True,
        tool_call_writer=seen.append,
    )

    assert seen == [event]
    assert texts == ["hello"]


def test_messages_thinking_sink_reaches_ace_parser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "thinking", "thinking": "Plan the file edits."},
                {"type": "text", "text": "Done."},
            ]
        },
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write(sys.argv[1] + '\\n')",
            json.dumps(event),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    text, stderr, return_code, usage = _stream_and_parse_messages_json_output(
        process,
        suppress_output=True,
        runtime="grok",
        tool_call_writer=lambda event: None,
        thinking_sink=True,
    )

    assert text == "Done."
    assert stderr == ""
    assert return_code == 0
    assert usage["input_tokens"] == 0
    blocks = read_codex_thinking(str(tmp_path))
    assert blocks is not None
    assert [block.text for block in blocks] == ["Plan the file edits."]
