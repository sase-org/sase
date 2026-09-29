"""Result-contract errors for gate-shell reclaim sweeps.

Covers the reclaim summary error capture/cap plus the summary dict contract.
The remaining reclaim coverage lives in ``test_reclaim_dispositions.py``
(single-gate dispositions) and ``test_reclaim_reconcile.py`` (handoff
reconcile). The original ``test_reclaim.py`` module remains as a facade that
lazily re-exports every test here under its historic import path.
"""

from __future__ import annotations

import pytest

import sase.gate_turn.reclaim as reclaim_mod
from sase.gate_turn.models import GateTurnRecord
from sase.gate_turn.reclaim import (
    GateTurnReclaimSummary,
    reclaim_pending_gate_turns,
)
from tests.gate_turn._reclaim_helpers import make_reclaim_record


def test_reclaim_records_error_details_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = make_reclaim_record(
        gate_id="gate-bad", member_agent_name="lane--gate-bad"
    )
    succeeding = make_reclaim_record(
        gate_id="gate-good", member_agent_name="lane--gate-good"
    )
    monkeypatch.setattr(
        reclaim_mod,
        "list_gate_turns",
        lambda *, project=None: [failing, succeeding],
    )

    def _reclaim_one(
        record: GateTurnRecord,
        *,
        now: float,
        grace_seconds: int,
    ) -> str | None:
        del now, grace_seconds
        if record.gate_id == "gate-bad":
            raise RuntimeError("bundle exploded")
        return "answered"

    monkeypatch.setattr(reclaim_mod, "_reclaim_one", _reclaim_one)

    summary = reclaim_pending_gate_turns()

    assert summary.scanned == 2
    assert summary.errors == 1
    assert summary.answered == 1
    assert len(summary.error_details) == 1
    detail = summary.error_details[0]
    assert detail.startswith("lane--gate-bad: RuntimeError: bundle exploded")


def test_reclaim_error_details_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    max_details = reclaim_mod._MAX_ERROR_DETAILS
    records = [
        make_reclaim_record(
            gate_id=f"gate-{index}", member_agent_name=f"lane--gate-{index}"
        )
        for index in range(max_details + 2)
    ]
    monkeypatch.setattr(
        reclaim_mod,
        "list_gate_turns",
        lambda *, project=None: records,
    )

    def _reclaim_one(
        record: GateTurnRecord,
        *,
        now: float,
        grace_seconds: int,
    ) -> str | None:
        del now, grace_seconds
        raise RuntimeError(record.gate_id)

    monkeypatch.setattr(reclaim_mod, "_reclaim_one", _reclaim_one)

    summary = reclaim_pending_gate_turns()

    assert summary.scanned == max_details + 2
    assert summary.errors == max_details + 2
    assert len(summary.error_details) == max_details


def test_reclaim_summary_to_dict_omits_error_details() -> None:
    summary = GateTurnReclaimSummary(
        scanned=2,
        answered=1,
        errors=1,
        error_details=("lane--gate: RuntimeError: boom",),
    )

    payload = summary.to_dict()

    assert payload == {
        "scanned": 2,
        "answered": 1,
        "stopped": 0,
        "timed_out": 0,
        "lost": 0,
        "accepted_unfinished": 0,
        "accepted_failed": 0,
        "accepted_owner_lost": 0,
        "errors": 1,
    }
    assert "error_details" not in payload
