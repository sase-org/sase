"""Historical marker readers and staged-handoff admission guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agent.pending_handoff import (
    GATE_PENDING_MARKER,
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
)


def test_pending_handoff_markers_are_named_constants() -> None:
    assert PENDING_HANDOFF_MARKERS == (
        PLAN_PENDING_MARKER,
        QUESTIONS_PENDING_MARKER,
        MONITOR_PENDING_MARKER,
        GATE_PENDING_MARKER,
        PIPE_PENDING_MARKER,
    )
    assert PIPE_PENDING_MARKER == ".sase_pipe_pending"


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
