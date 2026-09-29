"""Single-gate reclaim dispositions for gate-shell reclaim sweeps.

Covers ``_reclaim_one`` bundle-expiry outcomes (accepted-unfinished deferral,
timeout/lost settlement, racing decisions, contradictory receipts) and the
bundle-less/unreadable branches (lane-lock deferral, lost settlement, stale
snapshots). Error-contract coverage lives in ``test_reclaim_errors.py`` and
handoff reconcile coverage in ``test_reclaim_reconcile.py``. The original
``test_reclaim.py`` module remains as a facade that lazily re-exports every
test here under its historic import path.
"""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

import pytest

import sase.gate_turn.reclaim as reclaim_mod
import sase.gate_turn.store as store_mod
from sase.gate_turn.lane_lock import gate_lane_lock
from sase.gate_turn.models import GateTurnRecord
from sase.notification_gates.decision import accept_gate_decision
from sase.notification_gates.executor import cancel_gate as real_cancel_gate
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.paths import CANCELLATION_FILENAME
from sase.notification_gates.service import create_gate
from tests._notification_gates_fixtures import gate_spec
from tests.gate_turn._cli_fixtures import (
    gate_turn_home,
    make_gate_turn,
)
from tests.gate_turn._reclaim_helpers import RECLAIM_PROJECT, make_reclaim_record

__all__ = ["gate_turn_home"]


def _record_for_bundle(bundle_path: Path, *, gate_id: str) -> GateTurnRecord:
    record = make_reclaim_record(gate_id=gate_id, member_agent_name=f"lane--{gate_id}")
    return dataclasses.replace(record, bundle_path=str(bundle_path))


def _settlement_recorder(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, str, str | None]]:
    """Stub the (slow, real-store-backed) shell settlement, recording calls."""
    settled: list[tuple[str, str, str | None]] = []

    def fake_settle(
        record: GateTurnRecord,
        *,
        gate_state: str,
        reason: str | None = None,
        **_kwargs: object,
    ) -> GateTurnRecord:
        settled.append((record.gate_id, gate_state, reason))
        return record

    monkeypatch.setattr(reclaim_mod, "settle_gate_turn", fake_settle)
    return settled


def _gate_deadline(bundle_path: Path) -> float:
    envelope, _adapter = load_and_verify_bundle(bundle_path)
    return float(envelope["created_at_unix"]) + float(envelope["gate_timeout_seconds"])


def test_reclaim_defers_an_accepted_unfinished_gate_without_settling(
    gate_turn_home: Path, gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = create_gate(gate_spec(request_id="accepted-unfinished", timeout=1.0))
    accept_gate_decision(result.bundle_path, ["accept"], {})
    record = _record_for_bundle(result.bundle_path, gate_id="accepted-unfinished")
    settled = _settlement_recorder(monkeypatch)
    deadline = _gate_deadline(result.bundle_path)

    # Well past both the review deadline and the reclaim grace window: the
    # accepted-unfinished disposition must still outrank them.
    outcome = reclaim_mod._reclaim_one(record, now=deadline + 10_000, grace_seconds=1)

    assert outcome == "accepted_unfinished"
    assert settled == []
    assert not (result.bundle_path / CANCELLATION_FILENAME).exists()
    assert not result.response_path.exists()


def test_reclaim_settles_an_unaccepted_expired_review_gate_as_timeout(
    gate_turn_home: Path, gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = create_gate(gate_spec(request_id="unaccepted-timeout", timeout=1.0))
    record = _record_for_bundle(result.bundle_path, gate_id="unaccepted-timeout")
    settled = _settlement_recorder(monkeypatch)
    deadline = _gate_deadline(result.bundle_path)

    outcome = reclaim_mod._reclaim_one(record, now=deadline + 1, grace_seconds=300)

    assert outcome == "timeout"
    assert settled == [("unaccepted-timeout", "timeout", "gate timed out")]
    cancellation = json.loads(
        (result.bundle_path / CANCELLATION_FILENAME).read_text(encoding="utf-8")
    )
    assert cancellation["reason"] == "timeout"


def test_reclaim_settles_an_unaccepted_expired_grace_gate_as_lost(
    gate_turn_home: Path, gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = create_gate(gate_spec(request_id="unaccepted-lost", timeout=1.0))
    record = _record_for_bundle(result.bundle_path, gate_id="unaccepted-lost")
    settled = _settlement_recorder(monkeypatch)
    deadline = _gate_deadline(result.bundle_path)

    outcome = reclaim_mod._reclaim_one(record, now=deadline + 1000, grace_seconds=1)

    assert outcome == "lost"
    assert settled == [("unaccepted-lost", "lost", "gate deadline grace passed")]
    cancellation = json.loads(
        (result.bundle_path / CANCELLATION_FILENAME).read_text(encoding="utf-8")
    )
    assert cancellation["reason"] == "grace_expired"


def test_reclaim_expired_review_yields_to_a_racing_acceptance(
    gate_turn_home: Path, gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A decision accepted between reclaim's check and its locked cancel wins."""
    result = create_gate(gate_spec(request_id="race-review", timeout=1.0))
    record = _record_for_bundle(result.bundle_path, gate_id="race-review")
    settled = _settlement_recorder(monkeypatch)
    deadline = _gate_deadline(result.bundle_path)

    def racing_cancel_gate(bundle_path: Path, **kwargs: object) -> dict[str, object]:
        accept_gate_decision(bundle_path, ["accept"], {})
        return real_cancel_gate(bundle_path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(reclaim_mod, "cancel_gate", racing_cancel_gate)

    outcome = reclaim_mod._reclaim_one(record, now=deadline + 1, grace_seconds=300)

    assert outcome == "accepted_unfinished"
    assert settled == []
    assert not (result.bundle_path / CANCELLATION_FILENAME).exists()


def test_reclaim_expired_grace_yields_to_a_racing_completion(
    gate_turn_home: Path, gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A response published between reclaim's check and its locked cancel wins."""
    result = create_gate(gate_spec(request_id="race-grace", timeout=1.0))
    record = _record_for_bundle(result.bundle_path, gate_id="race-grace")
    settled = _settlement_recorder(monkeypatch)
    deadline = _gate_deadline(result.bundle_path)

    def racing_cancel_gate(bundle_path: Path, **kwargs: object) -> dict[str, object]:
        from sase.notification_gates.executor import execute_gate_selection

        execute_gate_selection(bundle_path, ["accept"], {})
        return real_cancel_gate(bundle_path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(reclaim_mod, "cancel_gate", racing_cancel_gate)

    outcome = reclaim_mod._reclaim_one(record, now=deadline + 1000, grace_seconds=1)

    assert outcome == "answered"
    assert settled == [("race-grace", "answered", "gate answered")]


def test_reclaim_raises_on_a_receipt_naming_a_different_gate(
    gate_turn_home: Path, gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.notification_gates.decision import DECISION_RECEIPT_FILENAME

    result = create_gate(gate_spec(request_id="contradictory-receipt"))
    accept_gate_decision(result.bundle_path, ["accept"], {})
    receipt_path = result.bundle_path / DECISION_RECEIPT_FILENAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["gate_id"] = "someone-elses-gate"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    record = _record_for_bundle(result.bundle_path, gate_id="contradictory-receipt")
    _settlement_recorder(monkeypatch)

    with pytest.raises(ValueError, match="invalid_gate_decision_receipt"):
        reclaim_mod._reclaim_one(record, now=time.time(), grace_seconds=300)


def _disk_record(project: str, artifacts_dir: str) -> GateTurnRecord:
    record = store_mod.read_gate_turn_marker(project, artifacts_dir)
    assert record is not None
    return record


def test_reclaim_defers_a_bundle_less_member_while_its_lane_is_locked(
    gate_turn_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A held lane lock means creation is still running: leave it pending."""
    artifacts_dir = make_gate_turn(
        RECLAIM_PROJECT,
        "20260929010001",
        "lane--gate",
        lane="lane",
        gate_id="gate-held",
    )
    record = _disk_record(RECLAIM_PROJECT, artifacts_dir)
    assert record.bundle_path is None
    settled = _settlement_recorder(monkeypatch)

    with gate_lane_lock(RECLAIM_PROJECT, "lane"):
        outcome = reclaim_mod._reclaim_one(record, now=time.time(), grace_seconds=300)

    assert outcome is None
    assert settled == []
    assert _disk_record(RECLAIM_PROJECT, artifacts_dir).gate_state == "pending"
    assert not (Path(artifacts_dir) / "done.json").exists()
    assert not (Path(artifacts_dir) / ".gate_followup.lock").exists()


def test_reclaim_settles_a_bundle_less_member_lost_once_its_lane_is_free(
    gate_turn_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A free lane lock plus no bundle preserves the crashed-creator outcome."""
    artifacts_dir = make_gate_turn(
        RECLAIM_PROJECT,
        "20260929010002",
        "lane--gate",
        lane="lane",
        gate_id="gate-free",
    )
    record = _disk_record(RECLAIM_PROJECT, artifacts_dir)
    assert record.bundle_path is None
    settled = _settlement_recorder(monkeypatch)

    outcome = reclaim_mod._reclaim_one(record, now=time.time(), grace_seconds=300)

    assert outcome == "lost"
    assert settled == [("gate-free", "lost", "gate bundle unreachable")]


def test_reclaim_defers_an_unreadable_bundle_while_its_lane_is_locked(
    gate_turn_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unreadable-bundle branch defers the same way the missing one does."""
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    artifacts_dir = make_gate_turn(
        RECLAIM_PROJECT,
        "20260929010003",
        "lane--gate",
        lane="lane",
        gate_id="gate-unreadable",
        gate_bundle_path=str(bundle_dir),
    )
    record = _disk_record(RECLAIM_PROJECT, artifacts_dir)
    assert Path(record.bundle_path or "").is_dir()
    monkeypatch.setattr(
        reclaim_mod,
        "load_and_verify_bundle",
        lambda _bundle: (_ for _ in ()).throw(RuntimeError("corrupt")),
    )
    settled = _settlement_recorder(monkeypatch)

    with gate_lane_lock(RECLAIM_PROJECT, "lane"):
        outcome = reclaim_mod._reclaim_one(record, now=time.time(), grace_seconds=300)

    assert outcome is None
    assert settled == []


def test_reclaim_spares_a_stale_snapshot_whose_bundle_is_now_reachable(
    gate_turn_home: Path, gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A snapshot without a bundle must not kill a creation that just landed."""
    result = create_gate(gate_spec(request_id="now-reachable"))
    artifacts_dir = make_gate_turn(
        RECLAIM_PROJECT,
        "20260929010004",
        "lane--gate",
        lane="lane",
        gate_id="now-reachable",
        gate_bundle_path=str(result.bundle_path),
    )
    fresh = _disk_record(RECLAIM_PROJECT, artifacts_dir)
    stale = dataclasses.replace(fresh, bundle_path=None)
    settled = _settlement_recorder(monkeypatch)

    outcome = reclaim_mod._reclaim_one(stale, now=time.time(), grace_seconds=300)

    assert outcome is None
    assert settled == []
