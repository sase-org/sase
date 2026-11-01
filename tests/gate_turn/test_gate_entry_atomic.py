"""Gate-entry atomicity: signal-safe entry and lost-gate withdrawal."""

from __future__ import annotations

import json
import os
import signal
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

from sase.gate_turn._lost_withdraw import withdraw_lost_gate
from sase.gate_turn._signal_guard import GateEntrySignal, gate_entry_signal_guard


def test_signal_guard_converts_sigterm_and_restores_handlers() -> None:
    prev_term = signal.getsignal(signal.SIGTERM)
    prev_hup = signal.getsignal(signal.SIGHUP)
    prev_int = signal.getsignal(signal.SIGINT)
    with pytest.raises(GateEntrySignal) as exc_info:
        with gate_entry_signal_guard():
            assert signal.getsignal(signal.SIGTERM) is not prev_term
            os.kill(os.getpid(), signal.SIGTERM)
    assert exc_info.value.signum == signal.SIGTERM
    assert signal.getsignal(signal.SIGTERM) is prev_term
    assert signal.getsignal(signal.SIGHUP) is prev_hup
    assert signal.getsignal(signal.SIGINT) is prev_int


def test_signal_guard_defers_second_signal_during_compensation() -> None:
    with pytest.raises(GateEntrySignal):
        with gate_entry_signal_guard():
            try:
                os.kill(os.getpid(), signal.SIGTERM)
            except GateEntrySignal:
                # Compensation is running; a second signal must not interrupt it.
                os.kill(os.getpid(), signal.SIGHUP)
                raise
    # Handlers are restored even after deferred delivery.
    assert isinstance(signal.getsignal(signal.SIGTERM), int | type(None) | object)


def test_launch_request_help_does_not_promise_a_wait() -> None:
    from sase.main import parser_launch

    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    parser_launch.register_launch_parser(subparsers)
    launch_parser = subparsers.choices["launch"]
    request_parser = None
    for action in launch_parser._subparsers._actions:  # type: ignore[attr-defined]
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict) and "request" in choices:
            request_parser = choices["request"]
            break
    assert request_parser is not None
    text = (
        str(getattr(request_parser, "description", "") or "")
        + "\n"
        + request_parser.format_help()
    )
    assert "Agent-side callers wait for the response" not in text
    assert "run it bare in the foreground" in text
    assert "no timeout, pipe," in text


@pytest.mark.parametrize(
    "skill_name", ["sase_run", "sase_gate", "sase_sudo", "sase_questions"]
)
def test_gate_skill_templates_forbid_timeout_pipe_background_job(
    skill_name: str,
) -> None:
    import re

    from sase.macro.loader import get_sase_package_skills_dir

    body = (get_sase_package_skills_dir() / f"{skill_name}.md").read_text(
        encoding="utf-8"
    )
    flat = re.sub(r"\s+", " ", body)
    assert "Never wrap" in flat
    assert "`timeout`, a pipe, or a background job" in flat


def _custom_request(request_id: str) -> dict[str, Any]:
    from tests._notification_gates_fixtures import custom_gate_spec

    spec = custom_gate_spec(request_id=request_id)
    spec["shell"] = {
        "pending_status": "GATE",
        "settled_status": "GATED",
        "workspace": "inherit",
        "next": {"prompt": "continue", "fork": "session", "output": ["results"]},
        "suffix": "--gate-test",
    }
    return spec


def _install_publish_fakes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record: Any
):
    from sase.gate_turn import transaction as transaction_module
    from sase.gate_turn.start_claim import GateClaimMove
    from sase.running_field import ClaimResult

    monkeypatch.setattr(transaction_module, "resolve_project_name", lambda: "proj")
    monkeypatch.setattr(
        transaction_module,
        "resolve_creator",
        lambda _project: record["creator"],
    )
    monkeypatch.setattr(transaction_module, "gate_lane_lock", lambda *_: nullcontext())
    monkeypatch.setattr(
        transaction_module, "find_gate_turn_by_gate_id", lambda *_: None
    )
    monkeypatch.setattr(transaction_module, "has_any_gate_turn", lambda *_: False)
    monkeypatch.setattr(
        transaction_module,
        "create_gate_turn_member",
        lambda *args, **kwargs: record["artifacts_dir"],
    )
    monkeypatch.setattr(
        transaction_module,
        "_read_required_record",
        lambda *_: record["record"],
    )
    monkeypatch.setattr(
        transaction_module,
        "_record_with_gate_result",
        lambda _project, gate_record, _result: gate_record,
    )
    restored: list[str] = []
    monkeypatch.setattr(
        transaction_module,
        "move_gate_turn_claim",
        lambda *a, **k: GateClaimMove(ClaimResult(True), None, None, "inherit"),
    )
    monkeypatch.setattr(
        transaction_module,
        "restore_gate_turn_claim",
        lambda *a, **k: restored.append("restored"),
    )
    settled: list[str] = []
    real_settle = transaction_module.settle_gate_turn

    def fake_settle(gate_record, **kwargs):
        settled.append(str(kwargs.get("gate_state")))
        return real_settle(gate_record, **kwargs)

    monkeypatch.setattr(transaction_module, "settle_gate_turn", fake_settle)
    return restored, settled


def test_signal_after_notification_append_compensates_gate(
    gate_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del gate_home
    from sase.agent.gate_intent import list_gate_intents
    from sase.finalizers.owned_turn import SASE_FINALIZER_OWNED_TURN_ENV
    from sase.gate_turn import transaction as transaction_module
    from sase.gate_turn._signal_guard import GateEntrySignal
    from sase.gate_turn._transaction_creator import CreatorContext
    from sase.gate_turn.models import GateTurnRecord
    from sase.gate_turn.transaction import create_gate_turn
    from sase.notification_gates.paths import bundle_paths

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.delenv(SASE_FINALIZER_OWNED_TURN_ENV, raising=False)

    member_dir = tmp_path / "member"
    member_dir.mkdir()
    record = GateTurnRecord(
        gate_id="signal-atomic-1",
        member_agent_name="agent--gate-test",
        lane="agent",
        project_name="proj",
        artifacts_dir=str(member_dir),
        timestamp="20260916120000",
        kind="custom",
        gate_state="pending",
        start_status="GATE",
        stop_status="GATED",
        accent="yellow",
        label="custom",
        reason="test",
        creator_agent="agent",
        bundle_path=None,
        notification_id=None,
        timeout_seconds=30.0,
        request_fingerprint=None,
        workspace_policy="inherit",
    )
    creator = CreatorContext(
        project_name="proj",
        project_file=str(tmp_path / "proj.sase"),
        artifacts_dir=str(tmp_path / "creator"),
        timestamp="20260916115959",
        target_name="agent",
        durable_lane="agent",
        meta={"name": "agent"},
        workspace_num=None,
        runner_pid=None,
        cl_name=None,
    )
    (Path(creator.artifacts_dir)).mkdir(parents=True, exist_ok=True)
    bundle = {"record": record, "creator": creator, "artifacts_dir": str(member_dir)}
    restored, settled = _install_publish_fakes(tmp_path, monkeypatch, bundle)
    (member_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "agent_session": "agent",
                "agent_session_role": "gate",
                "gate_id": "signal-atomic-1",
                "gate_kind": "custom",
                "gate_state": "pending",
                "gate_start_status": "GATE",
                "gate_stop_status": "GATED",
                "gate_label": "custom",
                "name": "agent--gate-test",
            }
        ),
        encoding="utf-8",
    )

    import sase.notifications.store as notifications_store

    real_append = notifications_store.append_notification_strict

    def append_then_interrupt(notification) -> None:
        real_append(notification)
        raise GateEntrySignal(signal.SIGTERM)

    monkeypatch.setattr(
        notifications_store, "append_notification_strict", append_then_interrupt
    )

    with pytest.raises(GateEntrySignal):
        create_gate_turn(_custom_request("signal-atomic-1"))

    # Intent is cleared for the converted termination signal.
    assert list_gate_intents(artifacts_dir) == []
    # Claim is restored and the member settles failed.
    assert restored == ["restored"]
    assert settled == ["failed"]
    # Notification is withdrawn: dismissed, no available pending entry, journal failed.
    from sase.notifications import pending_actions
    from sase.notifications.store import load_notifications

    paths = bundle_paths("custom", "signal-atomic-1")
    journal = json.loads(paths.journal.read_text(encoding="utf-8"))
    assert journal["state"] == "failed"
    notifications = load_notifications(include_dismissed=True)
    assert len(notifications) == 1
    assert notifications[0].dismissed is True
    actions = pending_actions.read_pending_action_store().get("actions", {})
    assert all(
        not isinstance(entry, dict)
        or entry.get("notification_id") != notifications[0].id
        or entry.get("state") != "available"
        for entry in actions.values()
    )


def test_run_gate_entry_releases_reservation_on_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.gate_turn import entry as entry_module
    from sase.gate_turn._signal_guard import GateEntrySignal

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    import sase.agent.staged_handoff as staged_handoff

    monkeypatch.setattr(staged_handoff, "staged_handoffs_enabled", lambda: False)
    monkeypatch.setattr(
        staged_handoff, "acquire_staging_reservation", lambda **_k: "reservation-1"
    )
    released: list[str] = []
    monkeypatch.setattr(
        staged_handoff,
        "release_staging_reservation",
        lambda reservation_id, **_k: released.append(reservation_id),
    )
    # Patch the lazy import used inside run_gate_entry/_run_legacy_creation.
    import sase.gate_turn as gate_turn_pkg

    def _raise_signal(*_a: object, **_k: object):
        raise GateEntrySignal(signal.SIGTERM)

    monkeypatch.setattr(gate_turn_pkg, "create_gate_turn", _raise_signal, raising=False)
    with pytest.raises(GateEntrySignal):
        entry_module.run_gate_entry(
            lambda: {"kind": "custom"}, command="sase gate create"
        )
    assert released == ["reservation-1"]


def _make_lost_record(
    tmp_path: Path,
    *,
    gate_id: str,
    kind: str = "custom",
    bundle_path=None,
    notification_id=None,
):
    from sase.gate_turn.models import GateTurnRecord

    return GateTurnRecord(
        gate_id=gate_id,
        member_agent_name="agent--gate",
        lane="agent",
        project_name="proj",
        artifacts_dir=str(tmp_path / gate_id),
        timestamp="20260916120000",
        kind=kind,
        gate_state="lost",
        start_status="GATE",
        stop_status="GATED",
        accent="yellow",
        label=kind,
        reason="gate bundle unreachable",
        creator_agent="agent",
        bundle_path=bundle_path,
        notification_id=notification_id,
        timeout_seconds=30.0,
        request_fingerprint=None,
        workspace_policy="inherit",
    )


def test_withdraw_lost_gate_clears_incomplete_bundle(
    gate_home: Path, tmp_path: Path
) -> None:
    del gate_home
    from sase.notification_gates.paths import bundle_paths
    from sase.notification_gates.service import create_gate
    from sase.notifications import pending_actions
    from sase.notifications.store import load_notifications
    from tests._notification_gates_fixtures import custom_gate_spec

    gate = create_gate(custom_gate_spec(request_id="lost-withdraw-1"))
    assert gate.notification_id is not None
    paths = bundle_paths("custom", "lost-withdraw-1")
    # Simulate the 16p state: gate-turn record has no bundle path.
    record = _make_lost_record(
        tmp_path,
        gate_id="lost-withdraw-1",
        bundle_path=None,
        notification_id=gate.notification_id,
    )
    assert withdraw_lost_gate(record) is True
    notifications = load_notifications(include_dismissed=True)
    assert len(notifications) == 1
    assert notifications[0].dismissed is True
    actions = pending_actions.read_pending_action_store().get("actions", {})
    assert all(
        not isinstance(entry, dict)
        or entry.get("notification_id") != notifications[0].id
        or entry.get("state") != "available"
        for entry in actions.values()
    )
    journal = json.loads(paths.journal.read_text(encoding="utf-8"))
    assert journal["state"] == "failed"


def test_withdraw_lost_gate_leaves_answered_gate_alone(
    gate_home: Path, tmp_path: Path
) -> None:
    del gate_home
    from sase.notification_gates.paths import RESPONSE_FILENAME, bundle_paths
    from sase.notification_gates.service import create_gate
    from sase.notifications.store import load_notifications
    from tests._notification_gates_fixtures import custom_gate_spec

    gate = create_gate(custom_gate_spec(request_id="lost-answered-1"))
    assert gate.notification_id is not None
    paths = bundle_paths("custom", "lost-answered-1")
    # Simulate an answered gate: response exists.
    (paths.root / RESPONSE_FILENAME).write_text("{}", encoding="utf-8")
    record = _make_lost_record(
        tmp_path,
        gate_id="lost-answered-1",
        bundle_path=None,
        notification_id=gate.notification_id,
    )
    assert withdraw_lost_gate(record) is False
    notifications = load_notifications(include_dismissed=True)
    assert len(notifications) == 1
    assert notifications[0].dismissed is False
    journal = json.loads(paths.journal.read_text(encoding="utf-8"))
    assert journal["state"] == "complete"
