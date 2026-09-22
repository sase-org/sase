"""MuseProvider JSONL stream-parser tests.

The stream tests run against sanitized captures from Muse Code release
``0.1.0-R708.1``. The fixtures are release-keyed on purpose: when Muse renames
a payload type, the right fix is a re-capture, not a loosened assertion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.llm_provider._subprocess_muse import MUSE_USAGE_ERROR_NOTE

from ._muse_provider_helpers import (
    _READ_TOOL_FIXTURE,
    _WRITE_BASH_FIXTURE,
    _delta,
    _envelope,
    _read_timestamps,
    _run_fixture_stream,
    _terminal,
)


def test_muse_stream_returns_the_terminal_text_without_delta_duplication() -> None:
    """The regression that matters most.

    The read-tool capture exits 0 while carrying `task.lifecycle.rejected`
    (`skip_if_running`) and `task.lifecycle.cancelled` (`main run completed`),
    and repeats the reply in both `run.output.delta` and
    `run.terminal.completed`. A Codex-style "any failure event is an error"
    parser manufactures a failure here, and appending the delta doubles the
    reply.
    """
    payload = _READ_TOOL_FIXTURE.read_text(encoding="utf-8")
    assert "task.lifecycle.rejected" in payload
    assert "task.lifecycle.cancelled" in payload

    content, stderr_content, return_code, usage = _run_fixture_stream(payload)

    assert return_code == 0
    assert content == "bravo"
    assert stderr_content == ""
    assert usage == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def test_muse_stream_parses_the_write_and_bash_capture() -> None:
    content, stderr_content, return_code, _ = _run_fixture_stream(
        _WRITE_BASH_FIXTURE.read_text(encoding="utf-8")
    )

    assert return_code == 0
    assert content == "DONE"
    assert stderr_content == ""


def test_muse_stream_streams_deltas_into_the_live_reply_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    content, _, _, _ = _run_fixture_stream(
        _READ_TOOL_FIXTURE.read_text(encoding="utf-8")
    )

    live_reply = (tmp_path / "live_reply.md").read_text(encoding="utf-8")
    assert live_reply == "bravo"
    assert content == "bravo"
    timestamps = (tmp_path / "live_reply_timestamps.jsonl").read_text(encoding="utf-8")
    assert json.loads(timestamps.splitlines()[0])["byte_offset"] == 0


def test_muse_stream_coalesces_deltas_into_one_live_reply_chunk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reply split mid-word and mid-inline-code stays one intact chunk."""
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    deltas = [
        "It doesn",
        "'t replace coding agents — it is `",
        "sase` — Structured\n",
        "Agentic Software Engineering.",
    ]
    reply = "".join(deltas)

    content, _, return_code, _ = _run_fixture_stream(
        "".join(_delta(text) for text in deltas) + _terminal(reply)
    )

    assert return_code == 0
    assert content == reply
    assert (tmp_path / "live_reply.md").read_text(encoding="utf-8") == reply
    assert [entry["byte_offset"] for entry in _read_timestamps(tmp_path)] == [0]


def test_muse_stream_opens_a_new_chunk_per_run_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    content, _, _, _ = _run_fixture_stream(
        _delta("first ", "cmd-1")
        + _delta("run", "cmd-1")
        + _terminal("first run", "cmd-1")
        + _delta("second ", "cmd-2")
        + _delta("run", "cmd-2")
        + _terminal("second run", "cmd-2")
    )

    assert content == "first run\n\nsecond run"
    live_reply = (tmp_path / "live_reply.md").read_text(encoding="utf-8")
    assert live_reply == "first run\n\nsecond run"
    # The second chunk's offset points at the separator, as read_reply_chunks
    # and the renderer's ``.strip()`` expect.
    assert [entry["byte_offset"] for entry in _read_timestamps(tmp_path)] == [
        0,
        len("first run"),
    ]


def test_muse_stream_splits_unkeyed_run_streams_at_the_terminal_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ids the terminal event is the only run boundary there is."""
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    content, _, _, _ = _run_fixture_stream(
        _delta("one ", None)
        + _delta("part", None)
        + _terminal("one part", None)
        + _delta("two", None)
        + _terminal("two", None)
    )

    assert content == "one part\n\ntwo"
    live_reply = (tmp_path / "live_reply.md").read_text(encoding="utf-8")
    assert live_reply == "one part\n\ntwo"
    assert len(_read_timestamps(tmp_path)) == 2


def test_muse_stream_salvages_concatenated_deltas_without_a_terminal_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    content, _, return_code, _ = _run_fixture_stream(
        _delta("It doesn") + _delta("'t break") + _delta(" words")
    )

    assert return_code == 0
    assert content == "It doesn't break words"
    diagnostics = [
        json.loads(line)
        for line in (tmp_path / "tool_calls_writer_errors.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    missing = [
        entry
        for entry in diagnostics
        if entry["reason"] == "muse_missing_run_terminal_event"
    ]
    assert len(missing) == 1
    assert missing[0]["streamed_deltas"] == 3


def test_muse_stream_salvage_joins_run_streams_with_a_blank_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    content, _, _, _ = _run_fixture_stream(
        _delta("al", "cmd-1")
        + _delta("pha", "cmd-1")
        + _delta("be", "cmd-2")
        + _delta("ta", "cmd-2")
    )

    assert content == "alpha\n\nbeta"


def test_muse_stream_prints_one_console_block_per_run_stream(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_fixture_stream(
        _delta("It doesn", "cmd-1")
        + _delta("'t split", "cmd-1")
        + _terminal("It doesn't split", "cmd-1")
        + _delta("next", "cmd-2")
        + _terminal("next", "cmd-2"),
        suppress_output=False,
    )

    assert capsys.readouterr().out == "It doesn't split\nnext\n"


def test_muse_stream_keeps_task_failures_out_of_a_successful_run() -> None:
    payload = _envelope(
        "task.lifecycle.rejected",
        {"event": {"kind": "rejected", "reason": "skip_if_running"}},
    ) + _envelope(
        "run.terminal.completed",
        {"terminal": "completed", "reason": None, "text": "all good"},
    )

    content, stderr_content, return_code, _ = _run_fixture_stream(payload)

    assert return_code == 0
    assert content == "all good"
    assert stderr_content == ""


def test_muse_stream_surfaces_task_diagnostics_when_the_process_failed() -> None:
    payload = _envelope(
        "task.lifecycle.rejected",
        {"event": {"kind": "rejected", "reason": "skip_if_running"}},
    )

    _, stderr_content, return_code, _ = _run_fixture_stream(payload, exit_code=1)

    assert return_code == 1
    assert "[muse] task rejected: skip_if_running" in stderr_content


def test_muse_stream_reports_a_non_completed_terminal_outcome() -> None:
    payload = _envelope(
        "run.terminal.failed",
        {"terminal": "failed", "reason": "model stream closed", "text": ""},
    )

    _, stderr_content, _, _ = _run_fixture_stream(payload, exit_code=1)

    assert "[muse] run terminal failed: model stream closed" in stderr_content


def test_muse_stream_labels_exit_code_two_as_a_usage_error() -> None:
    _, stderr_content, return_code, _ = _run_fixture_stream(
        _envelope("run.terminal.completed", {"terminal": "completed", "text": "hello"}),
        exit_code=2,
        stderr="error: unexpected argument '--nope'\n",
    )

    assert return_code == 2
    assert "--nope" in stderr_content
    assert MUSE_USAGE_ERROR_NOTE in stderr_content


def test_muse_stream_tolerates_unknown_payload_types_and_newer_schemas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    payload = _envelope("run.telepathy.vibed", {"text": "ignored"}) + _envelope(
        "run.terminal.completed",
        {"terminal": "completed", "text": "still fine"},
        schema_version=99,
        payload_schema_version=42,
    )

    content, stderr_content, return_code, _ = _run_fixture_stream(payload)

    assert return_code == 0
    assert content == "still fine"
    assert stderr_content == ""

    diagnostics = [
        json.loads(line)
        for line in (tmp_path / "tool_calls_writer_errors.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    ahead = [
        d for d in diagnostics if d["reason"] == "muse_stdout_schema_version_ahead"
    ]
    assert ahead and ahead[0]["schema_version"] == 99
    assert ahead[0]["payload_schema_version"] == 42


def test_muse_stream_records_a_diagnostic_for_undecodable_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    content, _, _, _ = _run_fixture_stream(
        '{"schema_version": 1, "payload_type"\n'
        + _envelope("run.terminal.completed", {"terminal": "completed", "text": "ok"})
    )

    assert content == "ok"
    reasons = {
        json.loads(line)["reason"]
        for line in (tmp_path / "tool_calls_writer_errors.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    }
    assert "muse_stdout_json_decode_error" in reasons
    assert "muse_stdout_envelope_unparsed" in reasons


def test_muse_stream_flags_a_missing_terminal_event_instead_of_returning_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    content, _, return_code, _ = _run_fixture_stream(
        _envelope("run.output.delta", {"text": "partial answer"}, record_type="status")
    )

    assert return_code == 0
    # The delta is the only text there is; losing it silently would be worse.
    assert content == "partial answer"
    reasons = {
        json.loads(line)["reason"]
        for line in (tmp_path / "tool_calls_writer_errors.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    }
    assert "muse_missing_run_terminal_event" in reasons
