from __future__ import annotations

import json
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


def test_read_collapses_v3_hook_pre_post_pair(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _hook_pre_record(
                tool_use_id="toolu_h1",
                tool_input_summary={"command": "ls /tmp"},
            ),
            _hook_post_record(
                tool_use_id="toolu_h1",
                duration_ms=123,
                tool_response_summary={"exit_code": 0, "stdout_preview": "alpha\n"},
            ),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.event == "ToolUse"
    assert entry.status == "success"
    assert entry.duration_ms == 123
    assert entry.source == "hook"
    assert entry.tool_input_summary["command"] == "ls /tmp"
    assert entry.tool_response_summary["stdout_preview"] == "alpha\n"


def test_read_keeps_orphan_v3_hook_pre_record_as_pending(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [_hook_pre_record(tool_use_id="toolu_h_orphan_pre")],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    assert entries[0].status == "pending"
    assert entries[0].source == "hook"


def test_read_keeps_orphan_v3_hook_post_record_with_tool_metadata(
    tmp_path: Path,
) -> None:
    """A PostToolUse without a matching PreToolUse should still display.

    This happens when SASE installs the hook mid-flight or when an earlier
    Pre payload was lost - the Post payload still carries enough fields
    (``tool_name``/``tool_input``) to render a useful row.
    """
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _hook_post_record(
                tool_use_id="toolu_h_orphan_post",
                tool_name="Read",
                tool_input_summary={"file_path": "src/sase/foo.py"},
                tool_response_summary={"content_preview": "class Foo:\n"},
            ),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.event == "ToolResult"
    assert entry.tool_name == "Read"
    assert entry.compact_target == "src/sase/foo.py"
    assert entry.detail == "class Foo:"


def test_hook_records_take_precedence_over_stream_records(tmp_path: Path) -> None:
    """When stream-derived rows AND hook rows exist for the same tool_use_id,
    the hook rows win - they carry richer fields and authoritative status."""
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _tool_use_record(tool_use_id="toolu_dup"),
            _tool_result_record(tool_use_id="toolu_dup"),
            _hook_pre_record(
                tool_use_id="toolu_dup",
                tool_input_summary={"command": "echo from-hook"},
            ),
            _hook_post_record(
                tool_use_id="toolu_dup",
                duration_ms=99,
                tool_response_summary={
                    "exit_code": 0,
                    "stdout_preview": "from-hook\n",
                },
            ),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.source == "hook"
    assert entry.duration_ms == 99
    assert entry.tool_input_summary["command"] == "echo from-hook"
    assert entry.tool_response_summary["stdout_preview"] == "from-hook\n"


def test_hook_precedence_does_not_drop_unrelated_stream_records(
    tmp_path: Path,
) -> None:
    """Stream rows for tool_use_ids not also present in hook records survive."""
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _tool_use_record(tool_use_id="toolu_stream_only"),
            _tool_result_record(tool_use_id="toolu_stream_only"),
            _hook_pre_record(tool_use_id="toolu_hook_only"),
            _hook_post_record(tool_use_id="toolu_hook_only"),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    ids = sorted(entry.tool_use_id or "" for entry in entries)
    assert ids == ["toolu_hook_only", "toolu_stream_only"]


def test_hook_records_aggregate_across_retry_phase_dirs(tmp_path: Path) -> None:
    root_dir = tmp_path / "ace-run" / "20260514140000"
    retry_dir = tmp_path / "ace-run" / "20260514140500"
    root_dir.mkdir(parents=True)
    retry_dir.mkdir(parents=True)
    (retry_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "retry_of_timestamp": root_dir.name,
                "retry_chain_root_timestamp": root_dir.name,
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        root_dir / "tool_calls.jsonl",
        [
            _hook_pre_record(
                tool_use_id="root_call",
                recorded_at="2026-05-14T14:00:00+00:00",
            ),
            _hook_post_record(
                tool_use_id="root_call",
                recorded_at="2026-05-14T14:00:01+00:00",
            ),
        ],
    )
    _write_jsonl(
        retry_dir / "tool_calls.jsonl",
        [
            _hook_pre_record(
                tool_use_id="retry_call",
                recorded_at="2026-05-14T14:05:00+00:00",
            ),
            _hook_post_record(
                tool_use_id="retry_call",
                recorded_at="2026-05-14T14:05:01+00:00",
            ),
        ],
    )

    agent = _agent(root_dir, retry_chain_root_timestamp=root_dir.name)
    entries = read_tool_calls_for_agent(agent)

    assert entries is not None
    assert [entry.tool_use_id for entry in entries] == ["root_call", "retry_call"]
    assert all(entry.source == "hook" for entry in entries)
