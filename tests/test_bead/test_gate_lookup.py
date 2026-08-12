"""Shared pending bead-gate lookup coverage."""

from __future__ import annotations

from pathlib import Path

from sase.bead.gate_lookup import _PendingBeadGate, find_pending_bead_gates
from sase.bead.snooze_gate import BEAD_SNOOZE_KIND
from sase.bead.task_gate import TASK_TRIAGE_KIND
from sase.notification_gates.durability import atomic_write_json, read_json_object
from sase.notification_gates.service import create_gate
from tests.test_bead.snooze_gate_test_helpers import bead_snooze_spec
from tests.test_bead.task_gate_test_helpers import task_triage_spec


def test_find_pending_bead_gates_reports_both_kinds_in_stable_order(
    gate_home: Path,
) -> None:
    del gate_home
    create_gate(
        task_triage_spec(
            request_id="z-triage",
            bead_id="sase-z",
            producer={"chop": "bead_task_triage"},
        )
    )
    create_gate(
        bead_snooze_spec(
            request_id="a-snooze",
            bead_id="sase-a",
            producer={"chop": "bead_task_triage"},
        )
    )

    assert find_pending_bead_gates((TASK_TRIAGE_KIND, BEAD_SNOOZE_KIND)) == [
        _PendingBeadGate(
            kind=BEAD_SNOOZE_KIND,
            request_id="a-snooze",
            project="sase",
            bead_id="sase-a",
            producer_chop="bead_task_triage",
        ),
        _PendingBeadGate(
            kind=TASK_TRIAGE_KIND,
            request_id="z-triage",
            project="sase",
            bead_id="sase-z",
            producer_chop="bead_task_triage",
        ),
    ]


def test_find_pending_bead_gates_skips_answered_and_cancelled_bundles(
    gate_home: Path,
) -> None:
    del gate_home
    answered = create_gate(task_triage_spec(request_id="answered"))
    cancelled = create_gate(task_triage_spec(request_id="cancelled"))
    pending = create_gate(task_triage_spec(request_id="pending"))
    atomic_write_json(answered.bundle_path / "response.json", {})
    atomic_write_json(cancelled.bundle_path / "cancellation.json", {})

    assert find_pending_bead_gates((TASK_TRIAGE_KIND,)) == [
        _PendingBeadGate(
            kind=TASK_TRIAGE_KIND,
            request_id="pending",
            project="sase",
            bead_id="sase-task.1",
            producer_chop=None,
        )
    ]
    assert (pending.bundle_path / "request.json").is_file()


def test_find_pending_bead_gates_skips_malformed_and_missing_payload(
    gate_home: Path,
) -> None:
    del gate_home
    malformed = create_gate(task_triage_spec(request_id="malformed"))
    missing_payload = create_gate(task_triage_spec(request_id="missing-payload"))
    malformed.bundle_path.joinpath("request.json").write_text("{", encoding="utf-8")
    envelope = read_json_object(missing_payload.bundle_path / "request.json")
    envelope.pop("payload")
    atomic_write_json(missing_payload.bundle_path / "request.json", envelope)

    assert find_pending_bead_gates((TASK_TRIAGE_KIND,)) == []


def test_find_pending_bead_gates_accepts_bundle_with_no_producer(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(task_triage_spec(request_id="no-producer"))
    envelope = read_json_object(gate.bundle_path / "request.json")
    envelope.pop("producer")
    atomic_write_json(gate.bundle_path / "request.json", envelope)

    assert find_pending_bead_gates((TASK_TRIAGE_KIND,)) == [
        _PendingBeadGate(
            kind=TASK_TRIAGE_KIND,
            request_id="no-producer",
            project="sase",
            bead_id="sase-task.1",
            producer_chop=None,
        )
    ]


def test_find_pending_bead_gates_treats_absent_kind_directory_as_empty(
    gate_home: Path,
) -> None:
    del gate_home

    assert find_pending_bead_gates((BEAD_SNOOZE_KIND,)) == []
