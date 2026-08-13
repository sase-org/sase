from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.tools import read_tool_calls_for_agent
from sase.llm_provider._tool_calls import append_grok_tool_call_event

from ._reader_helpers import _agent


@pytest.fixture
def artifacts_dir(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "ace-run" / "20260813140000"
    with patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": str(path)}):
        yield path


def test_read_tool_calls_for_agent_collapses_grok_bash_stream_records(
    artifacts_dir: Path,
) -> None:
    _append_grok_pair(
        artifacts_dir,
        tool_use_id="call-bash-1",
        raw_tool_name="run_terminal_command",
        tool_input={"command": "wc -c hello.txt", "description": "Count bytes"},
        result={
            "type": "Bash",
            "output": [53, 32, 104, 101, 108, 108, 111],
            "output_for_prompt": "exit: 0\n5 hello.txt\n",
            "exit_code": 0,
            "command": "wc -c hello.txt",
            "truncated": False,
            "signal": None,
            "timed_out": False,
            "description": "Count bytes",
            "current_dir": "/tmp/probe",
            "total_bytes": 12,
        },
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.runtime == "grok"
    assert entry.event == "ToolUse"
    assert entry.status == "success"
    assert entry.display_tool_name == "Bash"
    assert entry.compact_target == "Count bytes"
    assert entry.detail == "exit 0 | exit: 0 5 hello.txt"


def test_read_tool_calls_for_agent_renders_grok_search_replace_path(
    artifacts_dir: Path,
) -> None:
    _append_grok_pair(
        artifacts_dir,
        tool_use_id="call-edit-1",
        raw_tool_name="search_replace",
        tool_input={
            "path": "/tmp/probe/hello.txt",
            "old_string": "",
            "new_string": "HELLO",
        },
        result={
            "type": "SearchReplace",
            "EditsApplied": {
                "old_string": "",
                "new_string": "HELLO",
                "tool_output_for_prompt": (
                    "The file /tmp/probe/hello.txt has been created."
                ),
                "absolute_path": "/tmp/probe/hello.txt",
                "edits": {"details": [{"line": 1}]},
            },
        },
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.runtime == "grok"
    assert entry.display_tool_name == "Edit"
    assert entry.compact_target == "/tmp/probe/hello.txt"
    assert entry.tool_response_summary["file_path"] == "/tmp/probe/hello.txt"
    assert entry.tool_response_summary["success"] is True


def test_read_tool_calls_for_agent_preserves_unmapped_grok_tool_name(
    artifacts_dir: Path,
) -> None:
    _append_grok_pair(
        artifacts_dir,
        tool_use_id="call-unknown-1",
        raw_tool_name="custom_probe_tool",
        tool_input={"alpha": 1, "beta": True},
        result={"type": "CustomProbe", "output_for_prompt": "custom ok"},
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.runtime == "grok"
    assert entry.display_tool_name == "custom_probe_tool"
    assert entry.compact_target == ""
    assert entry.tool_input_summary == {"input_keys": ["alpha", "beta"]}
    assert entry.detail == "custom ok"


def test_read_tool_calls_for_agent_handles_grok_non_json_result_content(
    artifacts_dir: Path,
) -> None:
    append_grok_tool_call_event(
        _assistant_event(
            tool_use_id="call-text-1",
            raw_tool_name="run_terminal_command",
            tool_input={"command": "printf plain"},
        )
    )
    append_grok_tool_call_event(
        _user_result_event("call-text-1", content="plain text result")
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.runtime == "grok"
    assert entry.display_tool_name == "Bash"
    assert entry.status == "success"
    assert entry.detail == "plain text result"


def _append_grok_pair(
    artifacts_dir: Path,
    *,
    tool_use_id: str,
    raw_tool_name: str,
    tool_input: dict[str, object],
    result: dict[str, object],
) -> None:
    append_grok_tool_call_event(
        _assistant_event(
            tool_use_id=tool_use_id,
            raw_tool_name=raw_tool_name,
            tool_input=tool_input,
        )
    )
    append_grok_tool_call_event(
        _user_result_event(tool_use_id, content=json.dumps(result))
    )
    assert (artifacts_dir / "tool_calls.jsonl").exists()


def _assistant_event(
    *,
    tool_use_id: str,
    raw_tool_name: str,
    tool_input: dict[str, object],
) -> dict[str, object]:
    return {
        "type": "assistant",
        "message": {
            "id": f"msg-{tool_use_id}",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": raw_tool_name,
                    "input": tool_input,
                }
            ],
        },
        "session_id": "session-grok",
        "uuid": f"uuid-{tool_use_id}-use",
    }


def _user_result_event(tool_use_id: str, *, content: str) -> dict[str, object]:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "tool_use_id": tool_use_id,
                    "type": "tool_result",
                    "content": content,
                }
            ],
        },
        "session_id": "session-grok",
        "uuid": f"uuid-{tool_use_id}-result",
    }
