from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.tools import (
    ToolCallEntry,
    derive_tool_call_status,
    discover_related_tool_artifact_dirs,
    read_tool_calls_for_agent,
)

from ._reader_helpers import (
    _agent,
    _record,
    _tool_result_record,
    _tool_use_record,
    _write_jsonl,
)


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


def test_read_tool_calls_for_agent_collapses_gemini_stream_pairs(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _tool_use_record(
                tool_use_id="gemini-tool-1",
                tool_name="Bash",
                runtime="gemini",
                tool_input_summary={"command": "printf hi"},
            ),
            _tool_result_record(
                tool_use_id="gemini-tool-1",
                tool_name="Bash",
                runtime="gemini",
                tool_response_summary={"preview": "hi\n"},
            ),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.runtime == "gemini"
    assert entry.display_tool_name == "Bash"
    assert entry.status == "success"
    assert entry.compact_target == "printf hi"
    assert entry.detail == "hi"


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


def test_status_derivation_for_failure_interrupt_and_subagent() -> None:
    assert derive_tool_call_status({"status": "FAILED"}) == "failure"
    assert derive_tool_call_status({"status": "cancelled"}) == "interrupted"
    assert derive_tool_call_status({"status": "in_progress"}) == "pending"
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
