"""Muse usage, tool-call, and model-identity artifact tests.

Every assertion runs off the sanitized captures from Muse Code release
``0.1.0-R708.1``. Muse's stdout stream carries no tool arguments and no token
counts, so these tests pin exactly what SASE can honestly recover: tool
records derived from ``edit_facts`` and result bodies, usage summed from the
session log SASE named through ``--session-id``, and the model Muse actually
configured.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._muse_session_usage import (
    _find_muse_session_log,
    read_muse_session_usage,
)
from sase.llm_provider._subprocess import stream_and_parse_muse_json_output
from sase.llm_provider._tool_calls import finalize_pending_tool_calls
from sase.llm_provider.muse import MuseProvider

_FIXTURES = Path(__file__).parent / "fixtures"
_READ_TOOL_FIXTURE = _FIXTURES / "muse_exec_read_tool_R708.1.jsonl"
_WRITE_BASH_FIXTURE = _FIXTURES / "muse_exec_write_bash_tools_R708.1.jsonl"
_SESSION_LOG_FIXTURE = _FIXTURES / "muse_session_log_usage_R708.1.jsonl"

_SESSION_ID = "141ac0ea-2b6d-4171-9604-378f72626a67"

# Summed from the three ``model_completed`` events in the session-log capture.
_EXPECTED_USAGE = {
    "input_tokens": 48093,
    "output_tokens": 479,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 31650,
}
_ZERO_USAGE = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
}


def _run_stream(
    payload: str,
    *,
    session_id: str | None = None,
    exit_code: int = 0,
) -> tuple[str, str, int, dict[str, int]]:
    """Replay *payload* on a real subprocess's stdout and parse the stream."""
    script = "import sys\nsys.stdout.write(sys.argv[1])\nsys.exit(int(sys.argv[2]))\n"
    process = subprocess.Popen(
        [sys.executable, "-c", script, payload, str(exit_code)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return stream_and_parse_muse_json_output(
        process, suppress_output=True, session_id=session_id
    )


def _envelope(payload_type: str, payload: dict[str, object]) -> str:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "record_type": "event",
                "durability": "durable",
                "payload_type": payload_type,
                "payload_schema_version": 1,
                "payload": payload,
            }
        )
        + "\n"
    )


def _tool_call_records(artifacts_dir: Path) -> list[dict[str, Any]]:
    path = artifacts_dir / "tool_calls.jsonl"
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _install_session_log(tmp_path: Path, session_id: str, body: str) -> Path:
    """Materialize a Muse session log under a fake ``XDG_DATA_HOME``."""
    session_dir = tmp_path / "muse" / "sessions" / "2026" / "08" / "07" / session_id
    session_dir.mkdir(parents=True)
    log_path = session_dir / "session.jsonl"
    log_path.write_text(body, encoding="utf-8")
    return log_path


# --- Tool-call artifacts ----------------------------------------------


def test_muse_read_tool_capture_produces_a_read_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    _run_stream(_READ_TOOL_FIXTURE.read_text(encoding="utf-8"))

    records = _tool_call_records(tmp_path)
    use = [r for r in records if r["event"] == "ToolUse"]
    result = [r for r in records if r["event"] == "ToolResult"]
    assert len(use) == 1
    assert len(result) == 1
    assert use[0]["tool_name"] == "Read"
    assert use[0]["status"] == "pending"
    assert use[0]["runtime"] == "muse"
    assert use[0]["tool_use_id"] == "call_019fdecacfeb7e62be3154921895d324"
    assert result[0]["tool_use_id"] == use[0]["tool_use_id"]
    assert result[0]["status"] == "success"
    # Muse never streams tool arguments, so the read target is recovered from
    # the result text rather than invented.
    assert "notes.txt" in json.dumps(result[0]["tool_input_summary"])


def test_muse_write_capture_recovers_the_path_from_edit_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    _run_stream(_WRITE_BASH_FIXTURE.read_text(encoding="utf-8"))

    results = [r for r in _tool_call_records(tmp_path) if r["event"] == "ToolResult"]
    write_result = next(r for r in results if r["tool_name"] == "Write")
    assert write_result["tool_input_summary"]["file_path"] == "out.txt"
    assert write_result["status"] == "success"


def test_muse_bash_capture_recovers_the_command_from_the_result_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    _run_stream(_WRITE_BASH_FIXTURE.read_text(encoding="utf-8"))

    results = [r for r in _tool_call_records(tmp_path) if r["event"] == "ToolResult"]
    bash_result = next(r for r in results if r["tool_name"] == "Bash")
    summary = bash_result["tool_input_summary"]
    assert summary["command"].startswith("hexdump -C out.txt")
    assert summary["description"] == "Verify out.txt content"
    assert bash_result["tool_response_summary"]["exit_code"] == 0


def test_muse_non_tool_tasks_never_become_tool_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``model.meta.response`` and reminder tasks share the tool lifecycle."""
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    payload = (
        _envelope(
            "task.lifecycle.proposed",
            {"event": {"task_id": "t1", "task_kind": "model.meta.response"}},
        )
        + _envelope(
            "task.lifecycle.proposed",
            {
                "event": {
                    "task_id": "t2",
                    "task_kind": "reminder.agent.plugin:tbh-reminders:scope-reminder",
                }
            },
        )
        + _envelope(
            "task.lifecycle.scheduled",
            {"event": {"task_id": "t1", "idempotency_key": "model:run:t1"}},
        )
        + _envelope(
            "run.terminal.completed",
            {"terminal": "completed", "reason": None, "text": "done"},
        )
    )

    _run_stream(payload)

    assert _tool_call_records(tmp_path) == []


def test_muse_pending_tool_call_is_finalized_at_stream_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    payload = _envelope(
        "task.lifecycle.proposed",
        {"event": {"task_id": "t1", "task_kind": "tool.bash"}},
    ) + _envelope(
        "task.lifecycle.scheduled",
        {"event": {"task_id": "t1", "idempotency_key": "tool:call_abc"}},
    )

    _run_stream(payload)
    finalize_pending_tool_calls(str(tmp_path), completed_at=None)

    records = _tool_call_records(tmp_path)
    assert [r["event"] for r in records] == ["ToolUse", "ToolResult"]
    assert records[-1]["status"] == "interrupted"
    assert records[-1]["is_interrupt"] is True
    assert records[-1]["tool_use_id"] == "call_abc"


def test_muse_tool_records_are_skipped_without_an_artifacts_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    content, _, return_code, _ = _run_stream(
        _WRITE_BASH_FIXTURE.read_text(encoding="utf-8")
    )

    assert return_code == 0
    assert content == "DONE"
    assert list(tmp_path.iterdir()) == []


# --- Usage from the session log ---------------------------------------


def test_muse_usage_is_summed_from_the_session_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _install_session_log(
        tmp_path, _SESSION_ID, _SESSION_LOG_FIXTURE.read_text(encoding="utf-8")
    )

    assert read_muse_session_usage(_SESSION_ID) == _EXPECTED_USAGE


def test_muse_usage_ignores_goal_usage_attribution_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``goal_usage_attribution`` repeats ``model_completed`` numbers."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    body = "".join(
        line + "\n"
        for line in _SESSION_LOG_FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip() and "model_completed" not in line
    )
    assert "goal_usage_attribution" in body
    _install_session_log(tmp_path, _SESSION_ID, body)

    assert read_muse_session_usage(_SESSION_ID) == _ZERO_USAGE


def test_muse_missing_session_log_degrades_to_zeroed_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    assert read_muse_session_usage(_SESSION_ID) == _ZERO_USAGE

    diagnostics = (tmp_path / "tool_calls_writer_errors.jsonl").read_text(
        encoding="utf-8"
    )
    assert "muse_session_log_not_found" in diagnostics


def test_muse_session_log_is_found_across_any_date_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The date components are globbed so a midnight-spanning run resolves."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    session_dir = tmp_path / "muse" / "sessions" / "2019" / "12" / "31" / _SESSION_ID
    session_dir.mkdir(parents=True)
    (session_dir / "session.jsonl").write_text("", encoding="utf-8")

    found = _find_muse_session_log(_SESSION_ID)

    assert found == session_dir / "session.jsonl"


def test_muse_stream_returns_the_session_log_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _install_session_log(
        tmp_path, _SESSION_ID, _SESSION_LOG_FIXTURE.read_text(encoding="utf-8")
    )

    _, _, return_code, usage = _run_stream(
        _WRITE_BASH_FIXTURE.read_text(encoding="utf-8"), session_id=_SESSION_ID
    )

    assert return_code == 0
    assert usage == _EXPECTED_USAGE


def test_muse_stream_usage_is_zeroed_without_a_session_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    _, _, _, usage = _run_stream(_WRITE_BASH_FIXTURE.read_text(encoding="utf-8"))

    assert usage == _ZERO_USAGE


def test_muse_usage_artifact_records_the_recovered_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    _install_session_log(
        tmp_path, _SESSION_ID, _SESSION_LOG_FIXTURE.read_text(encoding="utf-8")
    )

    _run_stream(_WRITE_BASH_FIXTURE.read_text(encoding="utf-8"), session_id=_SESSION_ID)

    written = json.loads((artifacts_dir / "usage.json").read_text(encoding="utf-8"))
    assert written == _EXPECTED_USAGE


# --- Model identity ---------------------------------------------------


def test_muse_records_the_model_it_actually_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closes the gap where an unresolved model/effort shows blank in SASE."""
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    _run_stream(_WRITE_BASH_FIXTURE.read_text(encoding="utf-8"), session_id=_SESSION_ID)

    metadata = json.loads((tmp_path / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata == {
        "model_id": "muse-spark-1.2-contributor",
        "muse_session_id": _SESSION_ID,
        "provider_id": "meta",
        "runtime": "muse",
    }


def test_muse_run_metadata_merges_across_retry_cycles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    (tmp_path / "run_metadata.json").write_text(
        json.dumps({"existing": "kept"}), encoding="utf-8"
    )

    _run_stream(_READ_TOOL_FIXTURE.read_text(encoding="utf-8"))

    metadata = json.loads((tmp_path / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["existing"] == "kept"
    assert metadata["model_id"] == "muse-spark-1.2-contributor"


def test_muse_hands_the_parser_the_session_id_it_passed_on_the_command_line() -> None:
    """The argv session id and the usage lookup key must be the same handle."""
    seen: dict[str, object] = {}

    def _capture(
        process: object,
        suppress_output: bool = False,
        *,
        session_id: str | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        del process, suppress_output
        seen["parser_session_id"] = session_id
        return ("done", "", 0, dict(_ZERO_USAGE))

    def _record(*args: object, **kwargs: object) -> MagicMock:
        del kwargs
        argv = list(args[0])  # type: ignore[arg-type]
        seen["argv_session_id"] = argv[argv.index("--session-id") + 1]
        return MagicMock()

    with (
        patch("sase.llm_provider.muse.subprocess.Popen", side_effect=_record),
        patch("sase.llm_provider.muse.provider_timer"),
        patch(
            "sase.llm_provider.muse.stream_and_parse_muse_json_output",
            side_effect=_capture,
        ),
    ):
        MuseProvider().invoke("task", model_tier="large", suppress_output=True)

    assert seen["parser_session_id"] == seen["argv_session_id"]


def test_muse_run_metadata_is_absent_when_the_stream_declares_no_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    payload = _envelope(
        "run.terminal.completed",
        {"terminal": "completed", "reason": None, "text": "done"},
    )

    _run_stream(payload)

    assert not (tmp_path / "run_metadata.json").exists()
