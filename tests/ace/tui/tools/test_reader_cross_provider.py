from __future__ import annotations

from pathlib import Path

from sase.ace.tui.tools import read_tool_calls_for_agent

from ._reader_helpers import (
    _agent,
    _hook_post_record,
    _hook_pre_record,
    _tool_result_record,
    _tool_use_record,
    _write_jsonl,
)


def test_read_tool_calls_for_agent_uses_one_contract_across_providers(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    shared_id = "provider-reused-call-id"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _tool_use_record(
                tool_use_id=shared_id,
                runtime="claude",
                source="stream",
                tool_input_summary={"command": "echo claude-stream"},
            ),
            _tool_result_record(
                tool_use_id=shared_id,
                runtime="claude",
                source="stream",
                tool_response_summary={
                    "exit_code": 0,
                    "stdout_preview": "claude-stream\n",
                },
            ),
            _hook_pre_record(
                tool_use_id=shared_id,
                tool_input_summary={"command": "echo claude-hook"},
            ),
            _hook_post_record(
                tool_use_id=shared_id,
                tool_response_summary={
                    "exit_code": 0,
                    "stdout_preview": "claude-hook\n",
                },
            ),
            _tool_use_record(
                tool_use_id=shared_id,
                runtime="codex",
                source="stream",
                tool_input_summary={"command": "echo codex"},
            ),
            _tool_result_record(
                tool_use_id=shared_id,
                runtime="codex",
                source="stream",
                tool_response_summary={
                    "exit_code": 0,
                    "output_preview": "codex\n",
                },
            ),
            _tool_use_record(
                tool_use_id=shared_id,
                runtime="gemini",
                source="stream",
                tool_input_summary={"command": "echo gemini"},
            ),
            _tool_result_record(
                tool_use_id=shared_id,
                runtime="gemini",
                source="stream",
                tool_response_summary={"preview": "gemini\n"},
            ),
            _tool_use_record(
                tool_use_id=shared_id,
                runtime="qwen",
                source="stream",
                tool_input_summary={"command": "echo qwen"},
            ),
            _tool_result_record(
                tool_use_id=shared_id,
                runtime="qwen",
                source="stream",
                tool_response_summary={"content_preview": "qwen\n"},
            ),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert [(entry.runtime, entry.source) for entry in entries] == [
        ("claude", "hook"),
        ("codex", "stream"),
        ("gemini", "stream"),
        ("qwen", "stream"),
    ]
    assert [entry.event for entry in entries] == ["ToolUse"] * 4
    assert [entry.status for entry in entries] == ["success"] * 4
    assert [entry.compact_target for entry in entries] == [
        "echo claude-hook",
        "echo codex",
        "echo gemini",
        "echo qwen",
    ]
    assert [entry.detail for entry in entries] == [
        "exit 0 | claude-hook",
        "exit 0 | codex",
        "gemini",
        "qwen",
    ]
