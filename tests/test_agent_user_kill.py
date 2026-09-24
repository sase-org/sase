"""Tests for shared user-kill helpers."""

from __future__ import annotations

import json
import signal
import threading
from pathlib import Path

from sase.agent.user_kill import (
    DEFAULT_TERMINATE_GRACE_SECONDS,
    USER_KILL_INTENT_MARKER,
    AgentTerminationResult,
    ensure_user_kill_intent,
    escalate_user_kill_in_background,
    request_user_kill,
)


def test_request_user_kill_writes_intent_before_sigterm(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    calls: list[int] = []
    monkeypatch.setattr("sase.agent.user_kill.pid_is_thread", lambda _pid: False)

    def fake_killpg(_pgid: int, sig: int) -> None:
        calls.append(sig)
        marker = artifacts_dir / USER_KILL_INTENT_MARKER
        assert marker.exists()
        data = json.loads(marker.read_text(encoding="utf-8"))
        assert data["pid"] == 1234
        assert data["source"] == "test"

    result = request_user_kill(
        1234,
        artifacts_dir=artifacts_dir,
        source="test",
        wait=False,
        killpg=fake_killpg,
    )

    assert result.success is True
    assert result.status == "killed"
    assert calls == [signal.SIGTERM]
    marker_data = json.loads(
        (artifacts_dir / USER_KILL_INTENT_MARKER).read_text(encoding="utf-8")
    )
    assert marker_data["result"]["status"] == "killed"


def test_request_user_kill_identity_mismatch_sends_no_signal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "process_identity": "boot-a:111"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.agent.user_kill.process_identity_matches",
        lambda _pid, _recorded: False,
    )
    monkeypatch.setattr("sase.agent.user_kill.pid_is_thread", lambda _pid: False)
    calls: list[int] = []

    def fake_killpg(_pgid: int, sig: int) -> None:
        calls.append(sig)

    result = request_user_kill(
        1234,
        artifacts_dir=artifacts_dir,
        source="test",
        wait=False,
        killpg=fake_killpg,
    )

    marker = artifacts_dir / USER_KILL_INTENT_MARKER
    marker_data = json.loads(marker.read_text(encoding="utf-8"))
    assert result.success is True
    assert result.status == "identity_mismatch"
    assert calls == []
    assert marker_data["result"]["status"] == "identity_mismatch"


def test_request_user_kill_wait_runs_the_verified_terminator(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    seen: dict[str, object] = {}

    def fake_terminate(pid: int, **kwargs: object) -> AgentTerminationResult:
        seen["pid"] = pid
        seen.update(kwargs)
        assert (artifacts_dir / USER_KILL_INTENT_MARKER).exists()
        return AgentTerminationResult(True, "killed", pid, pid)

    monkeypatch.setattr(
        "sase.agent.user_kill.terminate_agent_processes", fake_terminate
    )

    result = request_user_kill(
        4321,
        artifacts_dir=artifacts_dir,
        source="test",
        wait=True,
    )

    assert result.status == "killed"
    assert seen["pid"] == 4321
    assert seen["grace_seconds"] == DEFAULT_TERMINATE_GRACE_SECONDS
    assert seen["marker_path"] == artifacts_dir / USER_KILL_INTENT_MARKER


def test_request_user_kill_background_escalates_through_the_terminator(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    escalated = threading.Event()
    seen: dict[str, object] = {}
    monkeypatch.setattr("sase.agent.user_kill.pid_is_thread", lambda _pid: False)

    def fake_terminate(pid: int, **kwargs: object) -> AgentTerminationResult:
        seen["pid"] = pid
        seen.update(kwargs)
        escalated.set()
        return AgentTerminationResult(True, "killed", pid, pid)

    monkeypatch.setattr(
        "sase.agent.user_kill.terminate_agent_processes", fake_terminate
    )

    result = request_user_kill(
        1234,
        artifacts_dir=artifacts_dir,
        source="test",
        wait=False,
        background=True,
        killpg=lambda _pgid, _sig: None,
    )

    assert result.status == "killed"
    assert escalated.wait(timeout=5)
    assert seen["pid"] == 1234


def test_escalate_in_background_runs_terminator_on_a_daemon_thread(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_terminate(pid: int, **kwargs: object) -> AgentTerminationResult:
        seen["pid"] = pid
        seen["thread"] = threading.current_thread()
        seen.update(kwargs)
        return AgentTerminationResult(True, "killed", pid, pid)

    monkeypatch.setattr(
        "sase.agent.user_kill.terminate_agent_processes", fake_terminate
    )

    thread = escalate_user_kill_in_background(
        99, artifacts_dir=tmp_path, grace_seconds=1.5
    )
    thread.join(timeout=5)

    assert thread.daemon is True
    assert seen["pid"] == 99
    assert seen["thread"] is thread
    assert seen["grace_seconds"] == 1.5


def test_ensure_user_kill_intent_keeps_an_existing_marker(tmp_path: Path) -> None:
    first = ensure_user_kill_intent(tmp_path, pid=1, source="ace_tui", reason="one")
    assert first is not None
    original = json.loads(first.read_text(encoding="utf-8"))

    second = ensure_user_kill_intent(tmp_path, pid=1, source="cleanup", reason="two")

    assert second == first
    assert json.loads(first.read_text(encoding="utf-8")) == original


def test_ensure_user_kill_intent_writes_a_missing_marker(tmp_path: Path) -> None:
    marker = ensure_user_kill_intent(tmp_path, pid=7, source="cleanup", reason="why")

    assert marker == tmp_path / USER_KILL_INTENT_MARKER
    assert marker is not None
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert (data["pid"], data["source"], data["reason"]) == (7, "cleanup", "why")
    assert ensure_user_kill_intent(None, pid=7, source="cleanup") is None
