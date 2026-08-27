"""Tests for shared user-kill helpers."""

from __future__ import annotations

import json
import signal
from pathlib import Path

from sase.agent.user_kill import (
    USER_KILL_INTENT_MARKER,
    _terminate_process_group,
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
        if sig == signal.SIGTERM:
            marker = artifacts_dir / USER_KILL_INTENT_MARKER
            assert marker.exists()
            data = json.loads(marker.read_text(encoding="utf-8"))
            assert data["pid"] == 1234
            assert data["source"] == "test"
        elif sig == 0:
            raise ProcessLookupError

    result = request_user_kill(
        1234,
        artifacts_dir=artifacts_dir,
        source="test",
        wait=True,
        killpg=fake_killpg,
    )

    assert result.success is True
    assert calls == [signal.SIGTERM, 0]


def test_terminate_process_group_escalates_after_grace(monkeypatch) -> None:
    calls: list[int] = []
    times = iter([0.0, 0.0, 1.0])
    monkeypatch.setattr("sase.agent.user_kill.pid_is_thread", lambda _pid: False)

    def fake_killpg(_pgid: int, sig: int) -> None:
        calls.append(sig)

    result = _terminate_process_group(
        2222,
        grace_seconds=0.1,
        poll_interval=0.0,
        killpg=fake_killpg,
        sleep_fn=lambda _seconds: None,
        monotonic_fn=lambda: next(times),
    )

    assert result.success is True
    assert result.status == "force_killed"
    assert result.escalated is True
    assert calls == [signal.SIGTERM, 0, signal.SIGKILL]


def test_terminate_process_group_skips_sigkill_when_process_exits(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr("sase.agent.user_kill.pid_is_thread", lambda _pid: False)

    def fake_killpg(_pgid: int, sig: int) -> None:
        calls.append(sig)
        if sig == 0:
            raise ProcessLookupError

    result = _terminate_process_group(
        3333,
        grace_seconds=0.1,
        poll_interval=0.0,
        killpg=fake_killpg,
        sleep_fn=lambda _seconds: None,
        monotonic_fn=iter([0.0, 0.0]).__next__,
    )

    assert result.success is True
    assert result.status == "killed"
    assert calls == [signal.SIGTERM, 0]


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
        wait=True,
        killpg=fake_killpg,
    )

    marker = artifacts_dir / USER_KILL_INTENT_MARKER
    marker_data = json.loads(marker.read_text(encoding="utf-8"))
    assert result.success is True
    assert result.status == "identity_mismatch"
    assert calls == []
    assert marker_data["result"]["status"] == "identity_mismatch"
