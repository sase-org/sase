"""Registry and write-path coverage for pending runner handoff markers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agent.pending_handoff import (
    MONITOR_PENDING_MARKER,
    PENDING_HANDOFF_MARKERS,
    PIPE_PENDING_MARKER,
    PLAN_PENDING_MARKER,
    QUESTIONS_PENDING_MARKER,
    has_pending_handoff,
)
from sase.agent.pending_handoff_write import (
    PendingHandoffError,
    handoff_guard,
    write_pending_handoff_marker,
)
from sase.axe.run_agent_runner_signals import _NON_MONITOR_HANDOFF_MARKERS


def test_pending_handoff_markers_are_named_constants() -> None:
    assert PENDING_HANDOFF_MARKERS == (
        PLAN_PENDING_MARKER,
        QUESTIONS_PENDING_MARKER,
        MONITOR_PENDING_MARKER,
        PIPE_PENDING_MARKER,
    )
    assert PIPE_PENDING_MARKER == ".sase_pipe_pending"


def test_non_monitor_handoff_markers_include_pipe() -> None:
    assert PIPE_PENDING_MARKER in _NON_MONITOR_HANDOFF_MARKERS
    assert MONITOR_PENDING_MARKER not in _NON_MONITOR_HANDOFF_MARKERS


def test_has_pending_handoff_detects_pipe_marker(tmp_path: Path) -> None:
    (tmp_path / PIPE_PENDING_MARKER).write_text("{}", encoding="utf-8")
    assert has_pending_handoff(str(tmp_path)) is True


def test_handoff_guard_names_missing_sase_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    with pytest.raises(PendingHandoffError, match="SASE_AGENT"):
        handoff_guard()


def test_handoff_guard_names_missing_sase_artifacts_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    with pytest.raises(PendingHandoffError, match="SASE_ARTIFACTS_DIR"):
        handoff_guard()


def test_handoff_guard_returns_artifacts_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    assert handoff_guard() == str(tmp_path)


def test_handoff_guard_refuses_existing_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    (tmp_path / PLAN_PENDING_MARKER).write_text("{}", encoding="utf-8")

    with pytest.raises(PendingHandoffError, match=PLAN_PENDING_MARKER):
        handoff_guard()


def test_second_marker_write_from_one_turn_raises(tmp_path: Path) -> None:
    first = write_pending_handoff_marker(
        QUESTIONS_PENDING_MARKER,
        {"questions": [{"question": "one"}]},
        artifacts_dir=str(tmp_path),
    )
    assert first.is_file()

    with pytest.raises(PendingHandoffError, match=QUESTIONS_PENDING_MARKER):
        write_pending_handoff_marker(
            PIPE_PENDING_MARKER,
            {"prompt": "continue"},
            artifacts_dir=str(tmp_path),
        )


def test_write_pending_handoff_marker_stamps_timestamp(tmp_path: Path) -> None:
    path = write_pending_handoff_marker(
        PLAN_PENDING_MARKER,
        {"plan_file": "/tmp/plan.md"},
        artifacts_dir=str(tmp_path),
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["plan_file"] == "/tmp/plan.md"
    assert isinstance(payload["timestamp"], float)


def test_write_pending_handoff_marker_keeps_explicit_timestamp(tmp_path: Path) -> None:
    path = write_pending_handoff_marker(
        MONITOR_PENDING_MARKER,
        {"monitor_id": "m1", "timestamp": 123.0},
        artifacts_dir=str(tmp_path),
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["timestamp"] == 123.0
