"""Replay test for the Muse Code ``1.4.13-R6996.1`` live-capture fixtures.

The fixtures are a sanitized capture of one real tool-using run: ``muse exec
--json`` with ``--model muse-spark-1.3`` (a non-Contributor model) running
three harmless shell commands with narration between them. Stdout carries
only ``task.lifecycle.*`` events mid-run plus final-answer deltas; the three
commentary messages live only in the session log. The fixtures are
release-keyed on purpose: when Muse renames a payload type or moves
commentary, the right fix is a re-capture, not a loosened assertion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ._muse_commentary_helpers import install_muse_session_log, run_muse_stream
from ._muse_provider_helpers import _read_timestamps

_FIXTURES = Path(__file__).parent / "fixtures"
_STDOUT_FIXTURE = _FIXTURES / "muse_exec_commentary_R6996.1.jsonl"
_SESSION_LOG_FIXTURE = _FIXTURES / "muse_session_log_commentary_R6996.1.jsonl"

_SESSION_ID = "d6cda56a-6ade-47cd-b9f9-448fdad79544"

_COMMENTARY = (
    "I'll run `echo capture-one` first to capture the output.",
    "Got `capture-one`; now I'll check the working directory and listing.",
    "Working directory noted; next I'll get the current UTC timestamp.",
)
_FINAL = (
    "1. `echo capture-one` output: `capture-one`.\n"
    "2. `pwd && ls`: working directory `/tmp/muse-capture/work` "
    "with no entries listed.\n"
    "3. Timestamp: `2026-10-27T03:17:33Z`.\n"
    "\n"
    "DONE: All three commands ran and reported.\n"
)


def test_live_capture_replay_streams_commentary_then_final_answer_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every captured commentary text lands as its own chunk, then the final.

    The returned content equals the terminal text (which matches the unphased
    final session-log message), usage matches the ``model_completed`` sums,
    and the 1.4.13 tool-call records still parse.
    """
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    install_muse_session_log(
        tmp_path, _SESSION_ID, _SESSION_LOG_FIXTURE.read_text(encoding="utf-8")
    )

    content, stderr_content, return_code, usage = run_muse_stream(
        _STDOUT_FIXTURE.read_text(encoding="utf-8"), session_id=_SESSION_ID
    )

    assert return_code == 0
    assert stderr_content == ""
    assert content == _FINAL

    live_reply = (artifacts / "live_reply.md").read_text(encoding="utf-8")
    assert live_reply == "\n\n".join([*_COMMENTARY, _FINAL])
    assert live_reply.count(_FINAL) == 1
    assert len(_read_timestamps(artifacts)) == 4

    assert usage == {
        "input_tokens": 121906,
        "output_tokens": 1066,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 90835,
    }

    results = [
        json.loads(line)
        for line in (artifacts / "tool_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and json.loads(line).get("event") == "ToolResult"
    ]
    assert [(entry["tool_name"], entry["status"]) for entry in results] == [
        ("Bash", "success"),
        ("Bash", "success"),
        ("Bash", "success"),
    ]
