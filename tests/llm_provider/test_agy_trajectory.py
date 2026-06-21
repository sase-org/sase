"""AgyProvider Antigravity trajectory database tests."""

import json
import sqlite3
import textwrap
from pathlib import Path

import pytest

from sase.llm_provider._subprocess_agy import (
    _snapshot_agy_conversations,
    analyze_agy_turn_progress,
)
from sase.llm_provider.agy import AgyProvider


def test_agy_provider_extracts_tool_calls_from_trajectory_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_agy = tmp_path / "agy"
    conversations_dir = tmp_path / "agy-home" / "conversations"
    fixture_db = tmp_path / "fixture.db"
    _write_agy_trajectory_db(
        fixture_db,
        [
            (1, 15, 3, _agy_payload("run_command", {"command": "echo provider"})),
            (2, 21, 3, _agy_payload({"stdout": "provider\n", "exit_code": 0})),
        ],
    )
    fake_agy.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import shutil
            import sys
            from pathlib import Path

            if "--version" in sys.argv:
                print("agy version 1.0.10", flush=True)
                raise SystemExit(0)

            conversations_dir = Path(os.environ["SASE_AGY_CONVERSATIONS_DIR"])
            cache_dir = conversations_dir.parent / "cache"
            conversations_dir.mkdir(parents=True, exist_ok=True)
            cache_dir.mkdir(parents=True, exist_ok=True)
            conversation_id = "provider-conv"
            shutil.copyfile(
                os.environ["AGY_FIXTURE_DB"],
                conversations_dir / f"{conversation_id}.db",
            )
            (cache_dir / "last_conversations.json").write_text(
                json.dumps({os.getcwd(): conversation_id}),
                encoding="utf-8",
            )
            print("agy fake ok", flush=True)
            """
        )
    )
    fake_agy.chmod(0o755)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGY_PATH", str(fake_agy))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGY_CONVERSATIONS_DIR", str(conversations_dir))
    monkeypatch.setenv("AGY_FIXTURE_DB", str(fixture_db))

    result = AgyProvider().invoke("do work", model_tier="large", suppress_output=True)

    records = [
        json.loads(line)
        for line in (artifacts / "tool_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert result.content == "agy fake ok"
    assert [record["event"] for record in records] == ["ToolUse", "ToolResult"]
    assert [record["runtime"] for record in records] == ["agy", "agy"]
    assert [record["source"] for record in records] == ["trajectory", "trajectory"]
    assert records[0]["tool_name"] == "Bash"
    assert records[0]["tool_input_summary"] == {"command": "echo provider"}
    assert records[1]["tool_response_summary"]["stdout_preview"] == "provider\n"


def test_agy_trajectory_progress_detects_zero_tool_steps(tmp_path: Path) -> None:
    conversations_dir = tmp_path / "conversations"
    cache_dir = tmp_path / "cache"
    conversations_dir.mkdir()
    cache_dir.mkdir()
    snapshot = _snapshot_agy_conversations(
        conversations_dir=conversations_dir,
        cache_dir=cache_dir,
        cwd=str(tmp_path),
    )

    progress = analyze_agy_turn_progress(snapshot)

    assert progress is not None
    assert progress.no_progress is True
    assert progress.reason == "trajectory_no_tool_steps"
    assert progress.tool_use_count == 0


def test_agy_trajectory_progress_detects_pending_run_command(
    tmp_path: Path,
) -> None:
    conversations_dir = tmp_path / "conversations"
    cache_dir = tmp_path / "cache"
    conversations_dir.mkdir()
    cache_dir.mkdir()
    snapshot = _snapshot_agy_conversations(
        conversations_dir=conversations_dir,
        cache_dir=cache_dir,
        cwd=str(tmp_path),
    )
    _write_agy_trajectory_db(
        conversations_dir / "pending.db",
        [
            (1, 15, 3, _agy_payload("run_command", {"command": "sleep 30"})),
            (2, 21, 1, _agy_payload({"stdout": "", "exit_code": None})),
        ],
    )

    progress = analyze_agy_turn_progress(snapshot)

    assert progress is not None
    assert progress.no_progress is True
    assert progress.reason == "trajectory_pending_run_command"
    assert progress.tool_use_count == 1


def test_agy_trajectory_progress_accepts_completed_tool_turn(
    tmp_path: Path,
) -> None:
    conversations_dir = tmp_path / "conversations"
    cache_dir = tmp_path / "cache"
    conversations_dir.mkdir()
    cache_dir.mkdir()
    snapshot = _snapshot_agy_conversations(
        conversations_dir=conversations_dir,
        cache_dir=cache_dir,
        cwd=str(tmp_path),
    )
    _write_agy_trajectory_db(
        conversations_dir / "complete.db",
        [
            (1, 15, 3, _agy_payload("run_command", {"command": "echo ok"})),
            (2, 21, 3, _agy_payload({"stdout": "ok\n", "exit_code": 0})),
        ],
    )

    progress = analyze_agy_turn_progress(snapshot)

    assert progress is not None
    assert progress.no_progress is False
    assert progress.reason == "trajectory_progress"
    assert progress.tool_use_count == 1


def test_agy_provider_trajectory_failure_is_best_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_agy = tmp_path / "agy"
    conversations_dir = tmp_path / "agy-home" / "conversations"
    fake_agy.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            if "--version" in sys.argv:
                print("agy version 1.0.10", flush=True)
                raise SystemExit(0)

            conversations_dir = Path(os.environ["SASE_AGY_CONVERSATIONS_DIR"])
            cache_dir = conversations_dir.parent / "cache"
            conversations_dir.mkdir(parents=True, exist_ok=True)
            cache_dir.mkdir(parents=True, exist_ok=True)
            conversation_id = "corrupt-conv"
            (conversations_dir / f"{conversation_id}.db").write_text(
                "not sqlite",
                encoding="utf-8",
            )
            (cache_dir / "last_conversations.json").write_text(
                json.dumps({os.getcwd(): conversation_id}),
                encoding="utf-8",
            )
            print("agy fake ok", flush=True)
            """
        )
    )
    fake_agy.chmod(0o755)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGY_PATH", str(fake_agy))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGY_CONVERSATIONS_DIR", str(conversations_dir))

    result = AgyProvider().invoke("do work", model_tier="large", suppress_output=True)

    assert result.content == "agy fake ok"
    assert not (artifacts / "tool_calls.jsonl").exists()
    diagnostics = [
        json.loads(line)
        for line in (artifacts / "tool_calls_writer_errors.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert diagnostics[0]["reason"] == "agy_trajectory_extraction_failed"


def _write_agy_trajectory_db(
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


def _agy_payload(*values: object) -> bytes:
    payload = _agy_field_varint(1, 15)
    for index, value in enumerate(values, start=10):
        if isinstance(value, str):
            data = value.encode("utf-8")
        else:
            data = json.dumps(value, sort_keys=True).encode("utf-8")
        payload += _agy_field_bytes(index, data)
    return payload


def _agy_field_varint(number: int, value: int) -> bytes:
    return _agy_varint((number << 3) | 0) + _agy_varint(value)


def _agy_field_bytes(number: int, value: bytes) -> bytes:
    return _agy_varint((number << 3) | 2) + _agy_varint(len(value)) + value


def _agy_varint(value: int) -> bytes:
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            encoded.append(byte | 0x80)
        else:
            encoded.append(byte)
            return bytes(encoded)
