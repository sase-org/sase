from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.tools import (
    ToolCallEntry,
    derive_tool_call_status,
    discover_related_tool_artifact_dirs,
    read_tool_calls_for_agent,
)


def _agent(artifacts_dir: Path, **kwargs: Any) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="DONE",
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        artifacts_dir=str(artifacts_dir),
        raw_suffix=artifacts_dir.name,
        **kwargs,
    )


def _record(**overrides: Any) -> dict[str, Any]:
    """Build a legacy v1 hook-event record (still readable for back-compat)."""
    data: dict[str, Any] = {
        "schema_version": 1,
        "recorded_at": "2026-05-14T14:00:00+00:00",
        "runtime": "claude",
        "event": "PostToolUse",
        "status": "success",
        "tool_name": "Bash",
        "tool_use_id": "toolu_default",
        "tool_input_summary": {"command": "pytest tests/foo.py"},
        "tool_response_summary": {"exit_code": 0, "stdout_preview": "ok\n"},
    }
    data.update(overrides)
    return data


def _tool_use_record(
    *,
    tool_use_id: str,
    tool_name: str = "Bash",
    recorded_at: str = "2026-05-14T14:00:00+00:00",
    tool_input_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "recorded_at": recorded_at,
        "runtime": "claude",
        "event": "ToolUse",
        "status": "pending",
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "tool_input_summary": tool_input_summary or {"command": "pytest tests/foo.py"},
        "tool_response_summary": {},
    }


def _tool_result_record(
    *,
    tool_use_id: str,
    status: str = "success",
    recorded_at: str = "2026-05-14T14:00:01+00:00",
    tool_response_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "recorded_at": recorded_at,
        "runtime": "claude",
        "event": "ToolResult",
        "status": status,
        "tool_use_id": tool_use_id,
        "tool_input_summary": {},
        "tool_response_summary": tool_response_summary
        or {"stdout_preview": "ok\n", "exit_code": 0},
    }


def _hook_pre_record(
    *,
    tool_use_id: str,
    tool_name: str = "Bash",
    recorded_at: str = "2026-05-14T14:00:00+00:00",
    tool_input_summary: dict[str, Any] | None = None,
    cwd: str = "/workspace",
    transcript_path: str = "/tmp/transcript.jsonl",
) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "recorded_at": recorded_at,
        "runtime": "claude",
        "source": "hook",
        "hook_event": "PreToolUse",
        "event": "ToolUse",
        "status": "pending",
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "session_id": "session-1",
        "transcript_path": transcript_path,
        "cwd": cwd,
        "tool_input_summary": tool_input_summary or {"command": "echo hi"},
        "tool_response_summary": {},
    }


def _hook_post_record(
    *,
    tool_use_id: str,
    tool_name: str = "Bash",
    status: str = "success",
    recorded_at: str = "2026-05-14T14:00:01+00:00",
    tool_input_summary: dict[str, Any] | None = None,
    tool_response_summary: dict[str, Any] | None = None,
    duration_ms: int | None = 42,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": 3,
        "recorded_at": recorded_at,
        "runtime": "claude",
        "source": "hook",
        "hook_event": "PostToolUse",
        "event": "ToolResult",
        "status": status,
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "session_id": "session-1",
        "tool_input_summary": tool_input_summary or {"command": "echo hi"},
        "tool_response_summary": tool_response_summary
        or {"exit_code": 0, "stdout_preview": "hi\n"},
    }
    if duration_ms is not None:
        record["duration_ms"] = duration_ms
    return record


def _write_jsonl(path: Path, records: list[dict[str, Any] | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            if isinstance(record, str):
                f.write(record + "\n")
            else:
                json.dump(record, f, sort_keys=True)
                f.write("\n")


def test_read_tool_calls_for_agent_returns_none_without_artifact(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    artifacts_dir.mkdir(parents=True)

    assert read_tool_calls_for_agent(_agent(artifacts_dir)) is None


def test_read_tool_calls_for_agent_distinguishes_empty_artifact(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "tool_calls.jsonl").write_text("", encoding="utf-8")

    assert read_tool_calls_for_agent(_agent(artifacts_dir)) == []


def test_read_tool_calls_for_agent_reads_v1_record(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _record(
                tool_name="Read",
                tool_input_summary={"file_path": "src/sase/foo.py"},
                tool_response_summary={"content_preview": "class Foo:\n"},
            )
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    assert entries[0].display_tool_name == "Read"
    assert entries[0].compact_target == "src/sase/foo.py"
    assert entries[0].detail == "class Foo:"


def test_read_tool_calls_for_agent_collapses_v2_use_result_pairs(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _tool_use_record(
                tool_use_id="toolu_a",
                tool_name="Bash",
                tool_input_summary={"command": "echo hi"},
            ),
            _tool_result_record(
                tool_use_id="toolu_a",
                tool_response_summary={"stdout_preview": "hi\n", "exit_code": 0},
            ),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.event == "ToolUse"
    assert entry.tool_use_id == "toolu_a"
    assert entry.status == "success"
    assert entry.tool_input_summary["command"] == "echo hi"
    assert entry.tool_response_summary["stdout_preview"] == "hi\n"


def test_read_tool_calls_for_agent_keeps_orphan_tool_use_as_pending(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [_tool_use_record(tool_use_id="toolu_orphan")],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    assert entries[0].status == "pending"
    assert entries[0].tool_use_id == "toolu_orphan"


def test_read_tool_calls_for_agent_propagates_failure_status(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _tool_use_record(tool_use_id="toolu_fail"),
            _tool_result_record(
                tool_use_id="toolu_fail",
                status="failure",
                tool_response_summary={"stderr_preview": "boom"},
            ),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert entries[0].status == "failure"


def test_read_tool_calls_for_agent_mixes_v1_and_v2(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _record(tool_use_id="legacy"),
            _tool_use_record(tool_use_id="toolu_new"),
            _tool_result_record(tool_use_id="toolu_new"),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    ids = [entry.tool_use_id for entry in entries]
    assert ids == ["legacy", "toolu_new"]


def test_read_tool_calls_for_agent_tolerates_malformed_lines(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            "{not json",
            _record(schema_version=99, tool_use_id="ignored"),
            _record(tool_use_id="usable"),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert [entry.tool_use_id for entry in entries or []] == ["usable"]


def test_read_tool_calls_for_agent_aggregates_related_phase_dirs(
    tmp_path: Path,
) -> None:
    root_dir = tmp_path / "ace-run" / "20260514140000"
    retry_dir = tmp_path / "ace-run" / "20260514140500"
    unrelated_dir = tmp_path / "ace-run" / "20260514141000"
    root_dir.mkdir(parents=True)
    retry_dir.mkdir(parents=True)
    unrelated_dir.mkdir(parents=True)
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
        [_record(recorded_at="2026-05-14T14:00:00+00:00", tool_use_id="root")],
    )
    _write_jsonl(
        retry_dir / "tool_calls.jsonl",
        [_record(recorded_at="2026-05-14T14:01:00+00:00", tool_use_id="retry")],
    )
    _write_jsonl(
        unrelated_dir / "tool_calls.jsonl",
        [_record(recorded_at="2026-05-14T14:02:00+00:00", tool_use_id="unrelated")],
    )

    agent = _agent(root_dir, retry_chain_root_timestamp=root_dir.name)
    related = discover_related_tool_artifact_dirs(agent, root_dir)
    entries = read_tool_calls_for_agent(agent)

    assert related == [root_dir, retry_dir]
    assert [entry.tool_use_id for entry in entries or []] == ["root", "retry"]


def test_read_tool_calls_for_agent_sorts_stably(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _record(recorded_at="2026-05-14T14:02:00+00:00", tool_use_id="late"),
            _record(recorded_at="2026-05-14T14:01:00+00:00", tool_use_id="early"),
            _record(recorded_at="2026-05-14T14:01:00+00:00", tool_use_id="same"),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert [entry.tool_use_id for entry in entries or []] == ["early", "same", "late"]


def test_unknown_tool_and_event_display_fallback() -> None:
    entry = ToolCallEntry(
        recorded_at="2026-05-14T14:00:00+00:00",
        runtime="qwen",
        event="ProviderSpecificEvent",
        status="success",
        tool_input_summary={"input_keys": ["alpha", "beta"]},
        tool_response_summary={"response_keys": ["result"]},
    )

    assert entry.display_tool_name == "ProviderSpecificEvent"
    assert entry.compact_target == "alpha, beta"
    assert entry.detail == "response: result"


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
    Pre payload was lost — the Post payload still carries enough fields
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
    the hook rows win — they carry richer fields and authoritative status."""
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


def test_status_derivation_for_failure_interrupt_and_subagent() -> None:
    assert (
        derive_tool_call_status({"event": "PostToolUseFailure", "status": "wat"})
        == "failure"
    )
    assert derive_tool_call_status({"is_interrupt": True}) == "interrupted"
    assert derive_tool_call_status({"event": "SubagentStart"}) == "subagent"
    assert (
        derive_tool_call_status({"tool_response_summary": {"success": False}})
        == "failure"
    )
    assert derive_tool_call_status({"event": "ToolUse"}) == "pending"
