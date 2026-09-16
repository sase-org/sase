"""Host adjudication for gate intent markers."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from sase.agent.gate_intent import (
    GATE_INTENT_PREFIX,
    atomic_write_json,
    begin_gate_intent,
    list_gate_intents,
)
from sase.agent.pending_handoff import GATE_PENDING_MARKER
from sase.llm_provider import gate_intent_guard as guard_module
from sase.llm_provider.gate_intent_guard import (
    GateIntentLostError,
    gate_intent_lost_error_for,
    raise_if_gate_intent_lost,
)


def _write_intent(
    artifacts_dir: Path,
    *,
    pid: int = 999_999_999,
    request_id: str | None = "sudo-one",
) -> Path:
    path = artifacts_dir / f"{GATE_INTENT_PREFIX}{pid}.json"
    atomic_write_json(
        path,
        {
            "kind": "sudo",
            "request_id": request_id,
            "source": "sase sudo request",
            "pid": pid,
            "process_identity": "",
            "timestamp": 1.0,
        },
    )
    return path


@pytest.fixture(autouse=True)
def _skip_member_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard_module, "_gate_shell_member_detail", lambda _intent: "")


def test_no_intent_is_noop(tmp_path: Path) -> None:
    raise_if_gate_intent_lost(str(tmp_path))


def test_pending_handoff_discards_intents_without_raise(tmp_path: Path) -> None:
    _write_intent(tmp_path)
    (tmp_path / GATE_PENDING_MARKER).write_text("{}", encoding="utf-8")

    raise_if_gate_intent_lost(str(tmp_path))

    assert list_gate_intents(tmp_path) == []


def test_dead_pid_raises_and_writes_evidence(tmp_path: Path) -> None:
    marker = _write_intent(tmp_path)

    with pytest.raises(GateIntentLostError) as exc_info:
        raise_if_gate_intent_lost(str(tmp_path))

    message = str(exc_info.value)
    assert "gate intent lost:" in message
    assert "sudo" in message
    assert "sudo-one" in message
    assert not marker.exists()
    evidence = json.loads((tmp_path / "gate_intent_lost.json").read_text())
    assert evidence["intents"][0]["request_id"] == "sudo-one"
    assert evidence["intents"][0]["pid_alive"] is False


def test_sigkilled_creator_raises_end_to_end(tmp_path: Path) -> None:
    code = (
        "import os, signal; "
        "from sase.agent.gate_intent import begin_gate_intent; "
        "begin_gate_intent('sudo', request_id='sudo-killed'); "
        "os.kill(os.getpid(), signal.SIGKILL)"
    )
    env = os.environ.copy()
    env["SASE_AGENT"] = "1"
    env["SASE_ARTIFACTS_DIR"] = str(tmp_path)

    result = subprocess.run([sys.executable, "-c", code], env=env, check=False)

    assert result.returncode == -signal.SIGKILL
    with pytest.raises(GateIntentLostError, match="sudo-killed"):
        raise_if_gate_intent_lost(str(tmp_path))


def test_live_pid_cleared_within_grace_is_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = _write_intent(tmp_path, pid=os.getpid())
    monkeypatch.setattr(guard_module, "GATE_INTENT_GRACE_SECONDS", 1.0)
    monkeypatch.setattr(guard_module, "_intent_pid_alive", lambda _intent: True)

    def _sleep(_seconds: float) -> None:
        marker.unlink()

    monkeypatch.setattr(guard_module.time, "sleep", _sleep)

    raise_if_gate_intent_lost(str(tmp_path))

    assert not (tmp_path / "gate_intent_lost.json").exists()


def test_live_pid_beyond_grace_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_intent(tmp_path, pid=os.getpid())
    monkeypatch.setattr(guard_module, "GATE_INTENT_GRACE_SECONDS", 0.01)
    monkeypatch.setattr(guard_module, "_intent_pid_alive", lambda _intent: True)
    monkeypatch.setattr(guard_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(GateIntentLostError) as exc_info:
        raise_if_gate_intent_lost(str(tmp_path))

    assert "still alive after grace period" in str(exc_info.value)


def test_runner_kill_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_intent(tmp_path)
    monkeypatch.setattr(guard_module, "_runner_was_killed", lambda: True)

    raise_if_gate_intent_lost(str(tmp_path))

    assert list_gate_intents(tmp_path)


def test_cause_is_chained_and_quoted(tmp_path: Path) -> None:
    cause = RuntimeError("provider said 429 Too Many Requests")
    _write_intent(tmp_path)

    converted = gate_intent_lost_error_for(cause, str(tmp_path))

    assert isinstance(converted, GateIntentLostError)
    assert converted.__cause__ is cause
    assert "provider error: provider said 429 Too Many Requests" in str(converted)


def test_agent_written_marker_from_current_process_can_be_adjudicated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    begin_gate_intent("sudo", request_id="sudo-live")
    monkeypatch.setattr(guard_module, "GATE_INTENT_GRACE_SECONDS", 0.01)
    monkeypatch.setattr(guard_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(GateIntentLostError, match="sudo-live"):
        raise_if_gate_intent_lost(str(tmp_path))
