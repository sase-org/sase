"""Explicit-cancel coverage for in-flight gate-turn creation."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import sase.gate_turn.cancel as cancel_mod
import sase.gate_turn.reclaim as reclaim_mod
from sase.gate_turn.cancel import cancel_gate_turn
from sase.gate_turn.lane_lock import gate_lane_lock
from sase.gate_turn.models import GateTurnRecord
from sase.gate_turn.store import read_gate_turn_marker
from tests.gate_turn._cli_fixtures import (
    gate_turn_home,
    make_gate_turn,
)

__all__ = ["gate_turn_home"]

_PROJECT = "proj"
_LANE = "lane"


def _pending_record(artifacts_dir: str) -> GateTurnRecord:
    record = read_gate_turn_marker(_PROJECT, artifacts_dir)
    assert record is not None and not record.is_terminal
    return record


def _settlement_recorder(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, str, str | None]]:
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

    # The lost branch settles inside reclaim's helper (reclaim_mod's
    # reference); the normal cancel path settles via cancel_mod's.
    monkeypatch.setattr(cancel_mod, "settle_gate_turn", fake_settle)
    monkeypatch.setattr(reclaim_mod, "settle_gate_turn", fake_settle)
    return settled


def test_cancel_returns_an_in_flight_member_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A held lane lock means "creating": cancel must not settle lost."""
    artifacts_dir = make_gate_turn(
        _PROJECT, "20260929000001", f"{_LANE}--gate", lane=_LANE, gate_id="gate-1"
    )
    record = _pending_record(artifacts_dir)
    assert record.bundle_path is None
    settled = _settlement_recorder(monkeypatch)

    with gate_lane_lock(_PROJECT, _LANE):
        result = cancel_gate_turn(record)

    assert result == record
    assert not result.is_terminal
    assert settled == []
    assert not (Path(artifacts_dir) / "done.json").exists()


def test_cancel_cancels_normally_once_the_bundle_is_reachable(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale bundle-less snapshot whose disk member has a bundle cancels."""
    from sase.notification_gates.service import create_gate
    from tests._notification_gates_fixtures import gate_spec

    del gate_home
    bundle_dir = str(create_gate(gate_spec(request_id="gate-2")).bundle_path)
    artifacts_dir = make_gate_turn(
        _PROJECT,
        "20260929000003",
        f"{_LANE}--gate",
        lane=_LANE,
        gate_id="gate-2",
        gate_bundle_path=bundle_dir,
    )
    fresh = _pending_record(artifacts_dir)
    assert fresh.bundle_path == bundle_dir
    stale = replace(fresh, bundle_path=None)
    cancelled: list[tuple[str, str]] = []
    monkeypatch.setattr(
        cancel_mod,
        "cancel_gate",
        lambda bundle, **kwargs: cancelled.append(
            (str(bundle), str(kwargs.get("reason")))
        ),
    )
    settled = _settlement_recorder(monkeypatch)

    result = cancel_gate_turn(stale)

    assert cancelled == [(bundle_dir, cancel_mod.DEFAULT_CANCEL_REASON)]
    assert settled == [("gate-2", "stopped", cancel_mod.DEFAULT_CANCEL_REASON)]
    assert result.gate_id == "gate-2"


def test_cancel_still_settles_a_truly_bundle_less_member_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A free lane lock plus no bundle anywhere preserves the lost outcome."""
    artifacts_dir = make_gate_turn(
        _PROJECT, "20260929000004", f"{_LANE}--gate", lane=_LANE, gate_id="gate-3"
    )
    record = _pending_record(artifacts_dir)
    settled = _settlement_recorder(monkeypatch)

    result = cancel_gate_turn(record)

    assert settled == [("gate-3", "lost", "gate bundle unreachable")]
    assert result.gate_id == "gate-3"


def test_cancel_leaves_a_missing_member_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A member deleted between the snapshot and cancel is not resurrected."""
    artifacts_dir = make_gate_turn(
        _PROJECT, "20260929000005", f"{_LANE}--gate", lane=_LANE, gate_id="gate-4"
    )
    record = _pending_record(artifacts_dir)
    settled = _settlement_recorder(monkeypatch)
    (Path(artifacts_dir) / "agent_meta.json").unlink()

    result = cancel_gate_turn(record)

    assert result == record
    assert settled == []


def test_cancel_returns_terminal_members_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = make_gate_turn(
        _PROJECT,
        "20260929000006",
        f"{_LANE}--gate",
        lane=_LANE,
        gate_id="gate-5",
        gate_state="answered",
    )
    record = read_gate_turn_marker(_PROJECT, artifacts_dir)
    assert record is not None and record.is_terminal
    settled = _settlement_recorder(monkeypatch)

    assert cancel_gate_turn(record) == record
    assert settled == []


def test_cancel_meta_bundle_path_round_trips() -> None:
    """Guard the fixture seam: ``gate_bundle_path`` meta reaches the record."""
    bundle_dir = make_gate_turn(
        _PROJECT, "20260929000007", f"{_LANE}--bundle", lane=_LANE, gate_id="gate-6"
    )
    artifacts_dir = make_gate_turn(
        _PROJECT,
        "20260929000008",
        f"{_LANE}--gate",
        lane=_LANE,
        gate_id="gate-6",
        gate_bundle_path=bundle_dir,
    )
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["gate_bundle_path"] == bundle_dir
    assert _pending_record(artifacts_dir).bundle_path == bundle_dir
