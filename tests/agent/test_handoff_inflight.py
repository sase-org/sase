"""Aborted-handoff evidence: in-flight markers, runner detection, records."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agent.handoff_inflight import (
    HANDOFF_ABORTED_FILENAME,
    HANDOFF_INFLIGHT_MARKER,
    adopt_or_record_aborted_handoff,
    _adopt_wait_seconds,
    clear_handoff_inflight_marker,
    _inflight_owner_alive,
    _load_handoff_aborted_record,
    merge_handoff_aborted_into_done_marker,
    _notify_handoff_aborted,
    _read_handoff_inflight_marker,
    _record_handoff_aborted,
    _wait_for_pending_handoff,
    write_handoff_inflight_marker,
)
from sase.agent.pending_handoff import MONITOR_PENDING_MARKER

_DEAD_PID = 2**30


@pytest.fixture()
def agent_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Run inside a fake agent artifacts dir."""
    monkeypatch.setenv("SASE_AGENT", "acme")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    return tmp_path


def _dead_marker(*, command: str = "sase monitor start -- just check") -> dict:
    return {
        "command": command,
        "lane": "acme",
        "agent": "acme",
        "pid": _DEAD_PID,
        "process_identity": "dead-boot:12345",
        "argv": ["sase", "monitor", "start"],
        "started_at": 1234.0,
    }


def test_write_returns_none_outside_an_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    assert write_handoff_inflight_marker("sase monitor start") is None
    assert not (tmp_path / HANDOFF_INFLIGHT_MARKER).exists()


def test_write_read_clear_lifecycle(agent_env: Path) -> None:
    path = write_handoff_inflight_marker(
        "sase monitor start -- just check", lane="acme"
    )
    assert path is not None and path.is_file()
    payload = _read_handoff_inflight_marker(str(agent_env))
    assert payload is not None
    assert payload["command"] == "sase monitor start -- just check"
    assert payload["lane"] == "acme"
    assert payload["pid"] == os.getpid()
    assert payload["argv"]
    assert payload["started_at"] > 0
    clear_handoff_inflight_marker(str(agent_env))
    assert _read_handoff_inflight_marker(str(agent_env)) is None


def test_read_missing_marker_is_none(tmp_path: Path) -> None:
    assert _read_handoff_inflight_marker(str(tmp_path)) is None
    assert _read_handoff_inflight_marker(None) is None


def test_owner_alive_for_current_process(agent_env: Path) -> None:
    write_handoff_inflight_marker("sase monitor start", lane="acme")
    payload = _read_handoff_inflight_marker(str(agent_env))
    assert payload is not None
    assert _inflight_owner_alive(payload) is True


def test_owner_dead_for_reaped_pid() -> None:
    assert _inflight_owner_alive(_dead_marker()) is False


def test_owner_dead_for_malformed_marker() -> None:
    assert _inflight_owner_alive({}) is False
    assert _inflight_owner_alive({"pid": "not-a-pid"}) is False
    assert _inflight_owner_alive({"pid": -3}) is False


def test_owner_dead_when_identity_mismatches_live_pid(
    agent_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recycled PID carrying a different start token is not the owner."""
    write_handoff_inflight_marker("sase monitor start", lane="acme")
    payload = _read_handoff_inflight_marker(str(agent_env))
    assert payload is not None
    monkeypatch.setattr(
        "sase.core.process_identity.process_identity_matches",
        lambda _pid, _recorded: False,
    )
    assert _inflight_owner_alive(payload) is False


def test_wait_for_pending_handoff_no_marker(tmp_path: Path) -> None:
    assert _wait_for_pending_handoff(str(tmp_path), timeout_seconds=0) is False


def test_wait_for_pending_handoff_sees_marker(tmp_path: Path) -> None:
    (tmp_path / MONITOR_PENDING_MARKER).write_text("{}", encoding="utf-8")
    assert _wait_for_pending_handoff(str(tmp_path), timeout_seconds=0) is True


def test_adopt_wait_seconds_default_and_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_HANDOFF_ADOPT_WAIT_SECONDS", raising=False)
    assert _adopt_wait_seconds() == pytest.approx(30.0)
    monkeypatch.setenv("SASE_HANDOFF_ADOPT_WAIT_SECONDS", "5")
    assert _adopt_wait_seconds() == pytest.approx(5.0)
    monkeypatch.setenv("SASE_HANDOFF_ADOPT_WAIT_SECONDS", "bogus")
    assert _adopt_wait_seconds() == pytest.approx(30.0)


def test_record_aborted_writes_files(tmp_path: Path) -> None:
    (tmp_path / "workflow_state.json").write_text(
        json.dumps({"activity": "RUNNING"}), encoding="utf-8"
    )
    record = _record_handoff_aborted(
        str(tmp_path), _dead_marker(), reason="handoff_process_dead"
    )
    assert record["command"] == "sase monitor start -- just check"
    assert record["reason"] == "handoff_process_dead"
    assert record["detected_at"] >= record["started_at"]
    stored = json.loads(
        (tmp_path / HANDOFF_ABORTED_FILENAME).read_text(encoding="utf-8")
    )
    assert stored == record
    state = json.loads((tmp_path / "workflow_state.json").read_text(encoding="utf-8"))
    assert state["handoff_aborted"] == record
    assert state["activity"] == "RUNNING"


def test_record_aborted_without_workflow_state(tmp_path: Path) -> None:
    """No workflow_state.json is created just to stamp the abort."""
    record = _record_handoff_aborted(
        str(tmp_path), _dead_marker(), reason="handoff_process_dead"
    )
    assert (tmp_path / HANDOFF_ABORTED_FILENAME).is_file()
    assert not (tmp_path / "workflow_state.json").exists()
    assert _load_handoff_aborted_record(str(tmp_path)) == record


def test_record_aborted_merges_into_existing_done_json(tmp_path: Path) -> None:
    (tmp_path / "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )
    record = _record_handoff_aborted(
        str(tmp_path), _dead_marker(), reason="handoff_process_dead"
    )
    done = json.loads((tmp_path / "done.json").read_text(encoding="utf-8"))
    assert done["handoff_aborted"] == record
    assert done["outcome"] == "completed"


def test_merge_aborted_into_done_marker_being_built(tmp_path: Path) -> None:
    record = _record_handoff_aborted(
        str(tmp_path), _dead_marker(), reason="handoff_process_dead"
    )
    marker: dict = {"outcome": "completed"}
    assert merge_handoff_aborted_into_done_marker(str(tmp_path), marker) is marker
    assert marker["handoff_aborted"] == record


def test_merge_aborted_keeps_explicit_marker_value(tmp_path: Path) -> None:
    _record_handoff_aborted(
        str(tmp_path), _dead_marker(), reason="handoff_process_dead"
    )
    marker: dict = {"handoff_aborted": {"reason": "explicit"}}
    merge_handoff_aborted_into_done_marker(str(tmp_path), marker)
    assert marker["handoff_aborted"] == {"reason": "explicit"}


def test_notify_names_agent_bead_and_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list = []
    monkeypatch.setattr("sase.notifications.store.upsert_notification", seen.append)
    _notify_handoff_aborted(
        _dead_marker(),
        agent_name="acme",
        assigned_bead_id="sase-18e.3",
        artifacts_dir=str(tmp_path),
    )
    assert len(seen) == 1
    notification = seen[0]
    assert notification.sender == "handoff_aborted"
    text = "\n".join(notification.notes)
    assert "acme" in text
    assert "sase-18e.3" in text
    assert "sase monitor start -- just check" in text
    assert "no follow-up agent will run" in text


def test_adopt_returns_none_without_marker(tmp_path: Path) -> None:
    assert adopt_or_record_aborted_handoff(str(tmp_path), agent_name="acme") is None


def test_adopt_clears_superseded_marker(tmp_path: Path) -> None:
    import sase.agent.handoff_inflight as inflight

    (tmp_path / HANDOFF_INFLIGHT_MARKER).write_text(
        json.dumps(_dead_marker()), encoding="utf-8"
    )
    (tmp_path / MONITOR_PENDING_MARKER).write_text("{}", encoding="utf-8")
    assert inflight.adopt_or_record_aborted_handoff(str(tmp_path)) is None
    assert not (tmp_path / HANDOFF_INFLIGHT_MARKER).exists()


def test_dead_owner_is_recorded_and_notified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.agent.handoff_inflight as inflight

    (tmp_path / HANDOFF_INFLIGHT_MARKER).write_text(
        json.dumps(_dead_marker()), encoding="utf-8"
    )
    seen: list = []
    monkeypatch.setattr("sase.notifications.store.upsert_notification", seen.append)
    record = inflight.adopt_or_record_aborted_handoff(
        str(tmp_path), agent_name="acme", assigned_bead_id="sase-18e.3"
    )
    assert record is not None
    assert record["reason"] == "handoff_process_dead"
    assert not (tmp_path / HANDOFF_INFLIGHT_MARKER).exists()
    assert (tmp_path / HANDOFF_ABORTED_FILENAME).is_file()
    assert len(seen) == 1


def test_dead_owner_record_survives_notification_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.agent.handoff_inflight as inflight

    (tmp_path / HANDOFF_INFLIGHT_MARKER).write_text(
        json.dumps(_dead_marker()), encoding="utf-8"
    )

    def _boom(_notification: object) -> None:
        raise RuntimeError("store down")

    monkeypatch.setattr("sase.notifications.store.upsert_notification", _boom)
    record = inflight.adopt_or_record_aborted_handoff(str(tmp_path))
    assert record is not None
    assert (tmp_path / HANDOFF_ABORTED_FILENAME).is_file()


def test_live_owner_adopted_after_bounded_wait(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.agent.handoff_inflight as inflight

    marker = _dead_marker() | {"pid": os.getpid()}
    (tmp_path / HANDOFF_INFLIGHT_MARKER).write_text(
        json.dumps(marker), encoding="utf-8"
    )
    monkeypatch.setattr(
        "sase.core.process_identity.process_identity_matches",
        lambda _pid, _recorded: True,
    )
    monkeypatch.setattr(inflight, "_wait_for_pending_handoff", lambda _d, **_k: True)
    assert inflight.adopt_or_record_aborted_handoff(str(tmp_path)) is None
    assert not (tmp_path / HANDOFF_INFLIGHT_MARKER).exists()


def test_live_owner_without_settlement_records_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.agent.handoff_inflight as inflight

    marker = _dead_marker() | {"pid": os.getpid()}
    (tmp_path / HANDOFF_INFLIGHT_MARKER).write_text(
        json.dumps(marker), encoding="utf-8"
    )
    monkeypatch.setattr(
        "sase.core.process_identity.process_identity_matches",
        lambda _pid, _recorded: True,
    )
    monkeypatch.setenv("SASE_HANDOFF_ADOPT_WAIT_SECONDS", "0")
    seen: list = []
    monkeypatch.setattr("sase.notifications.store.upsert_notification", seen.append)
    assert inflight.adopt_or_record_aborted_handoff(str(tmp_path)) is None
    assert (tmp_path / HANDOFF_INFLIGHT_MARKER).is_file()
    assert not (tmp_path / HANDOFF_ABORTED_FILENAME).exists()
    assert seen == []


def test_recovery_evidence_names_killed_handoff() -> None:
    from sase.finalizers.declaration_recovery_evidence import (
        build_recovery_evidence,
    )

    context = SimpleNamespace(context=SimpleNamespace(obligations=()))
    evidence = build_recovery_evidence(
        context=context,  # type: ignore[arg-type]
        original_prompt=None,
        response_text="",
        artifacts_dir=None,
        handoff_aborted={"command": "sase monitor start -- just check"},
    )
    assert "sase monitor start -- just check" in evidence
    assert "killed before the monitor started" in evidence
    assert "no follow-up agent will run" in evidence


def test_recovery_evidence_without_abort_has_no_handoff_section() -> None:
    from sase.finalizers.declaration_recovery_evidence import (
        build_recovery_evidence,
    )

    context = SimpleNamespace(context=SimpleNamespace(obligations=()))
    evidence = build_recovery_evidence(
        context=context,  # type: ignore[arg-type]
        original_prompt=None,
        response_text="",
        artifacts_dir=None,
    )
    assert "Handoff attempt" not in evidence


def test_pending_write_supersedes_inflight_marker(tmp_path: Path) -> None:
    from sase.turns.handoff import write_turn_pending_marker

    (tmp_path / HANDOFF_INFLIGHT_MARKER).write_text(
        json.dumps(_dead_marker()), encoding="utf-8"
    )
    write_turn_pending_marker(
        MONITOR_PENDING_MARKER, {"monitor_id": "m1"}, str(tmp_path)
    )
    assert (tmp_path / MONITOR_PENDING_MARKER).is_file()
    assert not (tmp_path / HANDOFF_INFLIGHT_MARKER).exists()
