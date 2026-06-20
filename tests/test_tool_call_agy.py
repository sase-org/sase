"""Tests for Antigravity trajectory tool-call extraction."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from sase.llm_provider._subprocess_agy import (
    append_agy_tool_call_events,
    _resolve_agy_conversation_dbs,
    _snapshot_agy_conversations,
)
from sase.llm_provider._tool_call_agy import (
    AgyTrajectoryStep,
    normalize_agy_trajectory_steps,
)


def test_normalize_agy_run_command_use_and_result_redacts_command() -> None:
    steps = [
        AgyTrajectoryStep(
            idx=10,
            step_type=15,
            status=3,
            step_payload=_payload(
                "run_command",
                {"cmd": "API_TOKEN=secret echo hi"},
            ),
        ),
        AgyTrajectoryStep(
            idx=11,
            step_type=21,
            status=3,
            step_payload=_payload({"stdout": "hi\n", "exit_code": 0}),
        ),
    ]

    records = normalize_agy_trajectory_steps(
        steps,
        conversation_id="conv-1",
        cwd="/workspace",
    )

    assert [record["event"] for record in records] == ["ToolUse", "ToolResult"]
    use, result = records
    assert use["runtime"] == "agy"
    assert use["source"] == "trajectory"
    assert use["tool_name"] == "Bash"
    assert use["tool_use_id"] == "conv-1:10"
    assert use["session_id"] == "conv-1"
    assert use["cwd"] == "/workspace"
    assert use["tool_input_summary"] == {"command": "API_TOKEN=[REDACTED] echo hi"}
    assert result["status"] == "success"
    assert result["tool_use_id"] == "conv-1:10"
    assert result["tool_response_summary"]["stdout_preview"] == "hi\n"
    assert result["tool_response_summary"]["exit_code"] == 0
    assert result["tool_response_summary"]["success"] is True


def test_normalize_agy_file_and_search_tools() -> None:
    steps = [
        AgyTrajectoryStep(1, 15, 3, _payload("view_file", {"path": "README.md"})),
        AgyTrajectoryStep(2, 8, 3, _payload({"content": "hello"})),
        AgyTrajectoryStep(
            3,
            15,
            3,
            _payload("write_file", {"path": "out.txt", "content": "abc"}),
        ),
        AgyTrajectoryStep(4, 9, 7, _payload({"error": "permission denied"})),
        AgyTrajectoryStep(
            5,
            15,
            3,
            _payload("search", {"query": "needle", "directory": "src"}),
        ),
        AgyTrajectoryStep(6, 132, 3, _payload({"result": "src/app.py:needle"})),
    ]

    records = normalize_agy_trajectory_steps(steps, conversation_id="conv-2")

    assert [record["tool_name"] for record in records] == [
        "Read",
        "Read",
        "Write",
        "Write",
        "Grep",
        "Grep",
    ]
    assert records[0]["tool_input_summary"] == {"file_path": "README.md"}
    assert records[1]["tool_response_summary"]["content_preview"] == "hello"
    assert records[2]["tool_input_summary"] == {
        "file_path": "out.txt",
        "content_length": 3,
    }
    assert records[3]["status"] == "failure"
    assert records[3]["tool_response_summary"]["success"] is False
    assert records[3]["tool_response_summary"]["is_error"] is True
    assert records[4]["tool_input_summary"] == {
        "pattern": "needle",
        "path": "src",
    }
    assert records[5]["tool_response_summary"]["result_preview"] == (
        "src/app.py:needle"
    )


def test_normalize_agy_unknown_tool_passthrough_and_unknown_steps() -> None:
    steps = [
        AgyTrajectoryStep(1, 98, 3, _payload("run_command", {"cmd": "ignored"})),
        AgyTrajectoryStep(
            2,
            15,
            3,
            _payload({"name": "custom_tool", "args": {"foo": "bar"}}),
        ),
        AgyTrajectoryStep(3, 21, 3, _payload({"result": "ok"})),
    ]

    records = normalize_agy_trajectory_steps(steps, conversation_id="conv-3")

    assert len(records) == 2
    assert records[0]["tool_name"] == "custom_tool"
    assert records[0]["tool_input_summary"] == {"input_keys": ["foo"]}
    assert records[1]["status"] == "success"


def test_normalize_agy_malformed_tool_payload_is_skipped() -> None:
    records = normalize_agy_trajectory_steps(
        [
            AgyTrajectoryStep(1, 15, 3, b"not protobuf"),
            AgyTrajectoryStep(2, 21, 3, _payload({"stdout": "orphan"})),
        ],
        conversation_id="conv-4",
    )

    assert records == []


def test_resolve_agy_conversation_dbs_filters_touched_by_cwd_map(
    tmp_path: Path,
) -> None:
    conversations_dir = tmp_path / "conversations"
    cache_dir = tmp_path / "cache"
    conversations_dir.mkdir()
    cache_dir.mkdir()
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    conv_a = conversations_dir / "conv-a.db"
    conv_b = conversations_dir / "conv-b.db"
    conv_a.write_text("a", encoding="utf-8")
    conv_b.write_text("b", encoding="utf-8")
    base_ns = 1_000_000_000
    os.utime(conv_a, ns=(base_ns, base_ns))
    os.utime(conv_b, ns=(base_ns, base_ns))
    snapshot = _snapshot_agy_conversations(
        conversations_dir=conversations_dir,
        cache_dir=cache_dir,
        cwd=str(cwd),
    )

    os.utime(conv_a, ns=(base_ns + 10, base_ns + 10))
    os.utime(conv_b, ns=(base_ns + 20, base_ns + 20))
    (cache_dir / "last_conversations.json").write_text(
        json.dumps({str(cwd.resolve()): "conv-b"}),
        encoding="utf-8",
    )

    assert _resolve_agy_conversation_dbs(snapshot) == [conv_b.resolve()]


def test_resolve_agy_conversation_dbs_rejects_cwd_map_mismatch(
    tmp_path: Path,
) -> None:
    conversations_dir = tmp_path / "conversations"
    cache_dir = tmp_path / "cache"
    conversations_dir.mkdir()
    cache_dir.mkdir()
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    conv = conversations_dir / "conv-a.db"
    conv.write_text("a", encoding="utf-8")
    base_ns = 1_000_000_000
    os.utime(conv, ns=(base_ns, base_ns))
    snapshot = _snapshot_agy_conversations(
        conversations_dir=conversations_dir,
        cache_dir=cache_dir,
        cwd=str(cwd),
    )
    os.utime(conv, ns=(base_ns + 10, base_ns + 10))
    (cache_dir / "last_conversations.json").write_text(
        json.dumps({str(cwd.resolve()): "different-conv"}),
        encoding="utf-8",
    )

    assert _resolve_agy_conversation_dbs(snapshot) == []


def test_append_agy_tool_call_events_reads_created_db(
    tmp_path: Path,
) -> None:
    conversations_dir = tmp_path / "conversations"
    cache_dir = tmp_path / "cache"
    artifacts_dir = tmp_path / "artifacts"
    cwd = tmp_path / "workspace"
    conversations_dir.mkdir()
    cache_dir.mkdir()
    artifacts_dir.mkdir()
    cwd.mkdir()
    snapshot = _snapshot_agy_conversations(
        conversations_dir=conversations_dir,
        cache_dir=cache_dir,
        cwd=str(cwd),
    )
    db_path = conversations_dir / "conv-created.db"
    _write_trajectory_db(
        db_path,
        [
            (1, 15, 3, _payload("run_command", {"command": "echo ok"})),
            (2, 21, 3, _payload({"stdout": "ok\n", "exit_code": 0})),
        ],
    )
    (cache_dir / "last_conversations.json").write_text(
        json.dumps({str(cwd.resolve()): "conv-created"}),
        encoding="utf-8",
    )

    written = append_agy_tool_call_events(
        snapshot,
        artifacts_dir=str(artifacts_dir),
    )

    records = [
        json.loads(line)
        for line in (artifacts_dir / "tool_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert written == 2
    assert [record["runtime"] for record in records] == ["agy", "agy"]
    assert [record["source"] for record in records] == ["trajectory", "trajectory"]
    assert records[0]["tool_input_summary"] == {"command": "echo ok"}
    assert records[1]["tool_response_summary"]["stdout_preview"] == "ok\n"


def test_append_agy_tool_call_events_reads_only_new_existing_db_steps(
    tmp_path: Path,
) -> None:
    conversations_dir = tmp_path / "conversations"
    cache_dir = tmp_path / "cache"
    artifacts_dir = tmp_path / "artifacts"
    cwd = tmp_path / "workspace"
    conversations_dir.mkdir()
    cache_dir.mkdir()
    artifacts_dir.mkdir()
    cwd.mkdir()
    db_path = conversations_dir / "conv-existing.db"
    _write_trajectory_db(
        db_path,
        [
            (1, 15, 3, _payload("run_command", {"command": "echo old"})),
            (2, 21, 3, _payload({"stdout": "old\n", "exit_code": 0})),
        ],
    )
    base_ns = 1_000_000_000
    os.utime(db_path, ns=(base_ns, base_ns))
    snapshot = _snapshot_agy_conversations(
        conversations_dir=conversations_dir,
        cache_dir=cache_dir,
        cwd=str(cwd),
    )
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO steps (idx, step_type, status, step_payload) "
            "VALUES (?, ?, ?, ?)",
            [
                (3, 15, 3, _payload("run_command", {"command": "echo new"})),
                (4, 21, 3, _payload({"stdout": "new\n", "exit_code": 0})),
            ],
        )
    os.utime(db_path, ns=(base_ns + 10, base_ns + 10))
    (cache_dir / "last_conversations.json").write_text(
        json.dumps({str(cwd.resolve()): "conv-existing"}),
        encoding="utf-8",
    )

    written = append_agy_tool_call_events(
        snapshot,
        artifacts_dir=str(artifacts_dir),
    )

    records = [
        json.loads(line)
        for line in (artifacts_dir / "tool_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert written == 2
    assert records[0]["tool_input_summary"] == {"command": "echo new"}
    assert records[1]["tool_response_summary"]["stdout_preview"] == "new\n"


def test_append_agy_tool_call_events_diagnoses_corrupt_db(
    tmp_path: Path,
) -> None:
    conversations_dir = tmp_path / "conversations"
    cache_dir = tmp_path / "cache"
    artifacts_dir = tmp_path / "artifacts"
    cwd = tmp_path / "workspace"
    conversations_dir.mkdir()
    cache_dir.mkdir()
    artifacts_dir.mkdir()
    cwd.mkdir()
    snapshot = _snapshot_agy_conversations(
        conversations_dir=conversations_dir,
        cache_dir=cache_dir,
        cwd=str(cwd),
    )
    (conversations_dir / "conv-corrupt.db").write_text("not sqlite", encoding="utf-8")
    (cache_dir / "last_conversations.json").write_text(
        json.dumps({str(cwd.resolve()): "conv-corrupt"}),
        encoding="utf-8",
    )

    written = append_agy_tool_call_events(
        snapshot,
        artifacts_dir=str(artifacts_dir),
    )

    diagnostics = [
        json.loads(line)
        for line in (artifacts_dir / "tool_calls_writer_errors.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert written == 0
    assert not (artifacts_dir / "tool_calls.jsonl").exists()
    assert diagnostics[0]["reason"] == "agy_trajectory_extraction_failed"


def _payload(*values: object) -> bytes:
    payload = _field_varint(1, 15)
    for index, value in enumerate(values, start=10):
        if isinstance(value, str):
            data = value.encode("utf-8")
        else:
            data = json.dumps(value, sort_keys=True).encode("utf-8")
        payload += _field_bytes(index, data)
    return payload


def _write_trajectory_db(
    path: Path,
    rows: list[tuple[int, int, int, bytes]],
) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE steps ("
            "idx INTEGER, "
            "step_type INTEGER, "
            "status INTEGER, "
            "step_payload BLOB"
            ")"
        )
        conn.executemany(
            "INSERT INTO steps (idx, step_type, status, step_payload) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )


def _field_varint(number: int, value: int) -> bytes:
    return _varint((number << 3) | 0) + _varint(value)


def _field_bytes(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            encoded.append(byte | 0x80)
        else:
            encoded.append(byte)
            return bytes(encoded)
