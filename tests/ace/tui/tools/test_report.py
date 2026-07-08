from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.tools import ToolCallEntry
from sase.ace.tui.tools import report as report_mod
from sase.ace.tui.tools.report import (
    SlowToolCallReportSpec,
    tool_call_report_path,
    write_tool_call_report,
)


def _entry(**overrides: object) -> ToolCallEntry:
    kwargs = {
        "recorded_at": "2026-07-07T14:35:02+00:00",
        "runtime": "codex",
        "event": "ToolUse",
        "status": "failure",
        "tool_name": "Bash",
        "tool_use_id": "call_1",
        "duration_ms": 134_000,
        "completed_at": "2026-07-07T14:37:16+00:00",
        "tool_input_summary": {"command": "cargo test --workspace"},
        "tool_response_summary": {
            "exit_code": 101,
            "stderr_preview": "assertion failed",
        },
        "session_id": "session-1",
        "cwd": "/repo",
        "permission_mode": "acceptEdits",
        "source_path": "/artifacts/tool_calls.jsonl",
        "line_number": 7,
        "artifact_dir": "/artifacts",
        "transcript_path": "/transcript.jsonl",
        "error": "command failed",
    }
    kwargs.update(overrides)
    return ToolCallEntry(**kwargs)  # type: ignore[arg-type]


def _spec(
    entry: ToolCallEntry, report_path: str = "/tmp/report.md"
) -> SlowToolCallReportSpec:
    return SlowToolCallReportSpec(
        entry=entry,
        source_label="code",
        agent_name="agent--code",
        report_path=report_path,
    )


def test_report_builder_renders_failure_metadata_and_output() -> None:
    report = report_mod._build_tool_call_report(_spec(_entry()))

    assert "# \u2718 Bash - failed after 2m 14s" in report
    assert "**Agent**: agent--code (chip: `code`)" in report
    assert "**Runtime**: codex" in report
    assert "`cargo test --workspace`" in report
    assert "## Tool Input" in report
    assert '"command": "cargo test --workspace"' in report
    assert "## Error" in report
    assert "command failed" in report
    assert "### exit_code" in report
    assert "101" in report
    assert "assertion failed" in report
    assert "Artifact: /artifacts/tool_calls.jsonl:7" in report
    assert "Transcript: /transcript.jsonl" in report


def test_report_builder_renders_success_without_empty_error_section() -> None:
    entry = _entry(
        status="success",
        tool_response_summary={
            "exit_code": 0,
            "stdout_preview": "tests passed",
        },
        error=None,
    )

    report = report_mod._build_tool_call_report(_spec(entry))

    assert "# \u2714 Bash - succeeded after 2m 14s" in report
    assert "## Error" not in report
    assert "No explicit error recorded." not in report
    assert "### stdout_preview" in report
    assert "tests passed" in report
    assert "Artifact: /artifacts/tool_calls.jsonl:7" in report


def test_report_builder_keeps_error_section_for_success_with_error_data() -> None:
    entry = _entry(
        status="success",
        tool_response_summary={"error": {"message": "unexpected warning"}},
        error=None,
    )

    report = report_mod._build_tool_call_report(_spec(entry))

    assert "# \u2714 Bash - succeeded after 2m 14s" in report
    assert "## Error" in report
    assert "unexpected warning" in report


def test_report_builder_handles_minimal_entry() -> None:
    entry = _entry(
        tool_use_id=None,
        duration_ms=None,
        completed_at=None,
        tool_input_summary={},
        tool_response_summary={},
        transcript_path=None,
        error=None,
    )

    report = report_mod._build_tool_call_report(_spec(entry))

    assert "# \u2718 Bash - failed" in report
    assert "No tool input summary recorded." in report
    assert "No explicit error recorded." in report
    assert "No recorded output summary fields were available." in report
    assert "Not recovered: transcript scan not requested." in report


def test_report_builder_surfaces_truncation_note() -> None:
    entry = _entry(
        tool_response_summary={
            "stdout_preview": "line 1\n...[truncated 120 chars]",
        },
    )

    report = report_mod._build_tool_call_report(_spec(entry))

    assert "stdout_preview" in report
    assert "truncation markers" in report


def test_report_path_is_stable_and_handles_missing_tool_use_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    entry = _entry(tool_use_id=None)

    first = tool_call_report_path(entry)
    second = tool_call_report_path(entry)

    assert first == second
    assert first.endswith(".md")
    assert Path(first).parent == tmp_path / ".sase" / "tool_call_reports"
    assert Path(first).name.startswith("bash-143502-")


def test_write_overwrites_and_prunes_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    entry = _entry(tool_response_summary={"stderr_preview": "first"})
    path = tool_call_report_path(entry)

    assert write_tool_call_report(_spec(entry, path)) == path
    assert "first" in Path(path).read_text(encoding="utf-8")

    updated = _entry(tool_response_summary={"stderr_preview": "second"})
    assert write_tool_call_report(_spec(updated, path)) == path
    assert "second" in Path(path).read_text(encoding="utf-8")

    for index in range(55):
        extra = _entry(
            tool_use_id=f"call_{index}",
            line_number=index + 100,
            tool_response_summary={"stderr_preview": f"extra {index}"},
        )
        extra_path = tool_call_report_path(extra)
        assert write_tool_call_report(_spec(extra, extra_path)) == extra_path

    report_dir = tmp_path / ".sase" / "tool_call_reports"
    assert len(list(report_dir.glob("*.md"))) == 50


def test_transcript_recovery_found(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"tool_use_id": "other", "content": "ignored"})
        + "\n"
        + json.dumps(
            {
                "tool_use_id": "call_1",
                "content": [{"type": "text", "text": "full failed output"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    entry = _entry(transcript_path=str(transcript))

    recovery = report_mod._recover_tool_call_output(entry)

    assert recovery.text == "full failed output"
    assert recovery.note == "Recovered from transcript."


def test_transcript_recovery_degrades_for_absent_missing_and_oversized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(json.dumps({"tool_use_id": "other"}) + "\n", encoding="utf-8")

    absent = report_mod._recover_tool_call_output(
        _entry(transcript_path=str(transcript))
    )
    missing = report_mod._recover_tool_call_output(
        _entry(transcript_path=str(tmp_path / "missing.jsonl"))
    )

    monkeypatch.setattr(report_mod, "_MAX_TRANSCRIPT_BYTES", 4)
    oversized = report_mod._recover_tool_call_output(
        _entry(transcript_path=str(transcript))
    )

    assert absent.text is None
    assert "no matching result text" in absent.note
    assert missing.text is None
    assert "file missing" in missing.note
    assert oversized.text is None
    assert "scan cap" in oversized.note
