"""Repro: reclaim must not settle an in-flight ``%auto`` gate creation as lost."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

import pytest

import sase.gate_turn.settlement as settlement_module
from sase.gate_turn import transaction as transaction_module
from sase.gate_turn.handoff import (
    CREATOR_LIVE_FOLLOWUP_LOCK_TIMEOUT_SECONDS,
    FOLLOWUP_LOCK_TIMEOUT_SECONDS,
)
from sase.gate_turn.lane_lock import gate_lane_lock as real_gate_lane_lock
from sase.gate_turn.models import GateTurnRecord
from sase.gate_turn.reclaim import reclaim_pending_gate_turns
from sase.gate_turn.store import GateTurnSnapshot
from sase.gate_turn.transaction import create_gate_turn
from tests.gate_turn._cli_fixtures import gate_turn_home
from tests.gate_turn.test_transaction_gate_intent import (
    _creation_result,
    _install_transaction_fakes,
    _record,
    _set_agent_env,
    _shell_gate_spec,
)

__all__ = ["gate_turn_home"]


def test_reclaim_does_not_settle_an_auto_gate_while_it_executes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repro for the approved-plan incident: reclaim ran mid auto-execution.

    ``create_gate()`` for an ``%auto`` gate executes the selected option
    commands inline while the creation transaction still holds the lane
    lock. A reclaim pass over a snapshot taken in that window must defer
    (``None``), and the creation must still settle ``answered``.
    """
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _set_agent_env(tmp_path, monkeypatch)
    record = _install_transaction_fakes(tmp_path, monkeypatch)
    # The shared fakes stub out the lane lock; this test needs the real one
    # so reclaim genuinely contends with the creation transaction.
    monkeypatch.setattr(transaction_module, "gate_lane_lock", real_gate_lane_lock)
    seen: dict[str, object] = {}

    def fake_create_gate(spec: object) -> object:
        del spec
        snapshot = GateTurnSnapshot(
            taken_at=0.0,
            gate_turns=(record,),
            agent_session_members={},
            record_count=1,
        )
        seen["summary"] = reclaim_pending_gate_turns(snapshot=snapshot)
        return _creation_result(tmp_path, auto=True)

    settled: list[str] = []

    def fake_settle(gate_record: GateTurnRecord, **kwargs: object) -> GateTurnRecord:
        del kwargs
        settled.append(gate_record.gate_id)
        return replace(gate_record, gate_state="answered")

    monkeypatch.setattr(transaction_module, "create_gate", fake_create_gate)
    monkeypatch.setattr(transaction_module, "settle_gate_turn", fake_settle)

    creation = create_gate_turn(_shell_gate_spec())

    summary = seen["summary"]
    assert summary is not None
    assert summary.scanned == 1
    assert summary.lost == 0
    assert summary.errors == 0
    assert settled == ["intent-one"]
    assert creation.record.is_terminal
    assert creation.record.gate_state == "answered"


def test_settle_gate_turn_uses_a_longer_lock_timeout_for_live_creators(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live creator waits out follow-up lock contention; others keep 5s."""
    assert CREATOR_LIVE_FOLLOWUP_LOCK_TIMEOUT_SECONDS == 60.0
    assert FOLLOWUP_LOCK_TIMEOUT_SECONDS == 5.0
    captured: list[tuple[str, float | None]] = []

    def recording_lock(artifacts_dir: str, *, timeout: float | None = None) -> object:
        captured.append((artifacts_dir, timeout))
        return nullcontext()

    monkeypatch.setattr(settlement_module, "with_gate_followup_lock", recording_lock)
    monkeypatch.setattr(
        settlement_module,
        "_settle_gate_turn_locked",
        lambda gate_record, **_kwargs: gate_record,
    )
    record = _record(tmp_path)

    settlement_module.settle_gate_turn(
        record, gate_state="answered", reason="auto", creator_live=True
    )
    settlement_module.settle_gate_turn(record, gate_state="answered", reason="manual")

    assert captured == [
        (
            record.artifacts_dir,
            CREATOR_LIVE_FOLLOWUP_LOCK_TIMEOUT_SECONDS,
        ),
        (record.artifacts_dir, FOLLOWUP_LOCK_TIMEOUT_SECONDS),
    ]
