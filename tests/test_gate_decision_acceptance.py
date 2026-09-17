"""Fast, durable decision acceptance ahead of slow gate execution.

Covers the behaviors specific to :mod:`sase.notification_gates.decision`:
the receipt stays visible and the notification stays dismissed while an
option command is still blocked, identical resubmissions replay instead of
re-accepting, a conflicting resubmission is rejected before any command
runs, racing submissions cannot both win, and a durably accepted decision
can no longer be cancelled. Execution-level behavior (response.json
contract, journal, adapters) is covered by ``test_notification_gate_execution.py``
and ``test_gate_executor_integrity.py``; this module only exercises the
acceptance boundary those tests already treat as a black box.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from typing import cast

import pytest

from sase.notification_gates.decision import (
    DECISION_RECEIPT_FILENAME,
    accept_gate_decision,
    receipt_acceptance_id,
)
from sase.notification_gates.durability import atomic_write_json
from sase.notification_gates.executor import cancel_gate, execute_gate_selection
from sase.notification_gates.failure_notifications import GATE_EXECUTION_FAILED_ACTION
from sase.notification_gates.journal import append_journal_event
from sase.notification_gates.models import GateError
from sase.notification_gates.poller import poll_gate
from sase.notification_gates.service import create_gate
from sase.notifications.store import load_notifications
from tests._notification_gates_fixtures import custom_gate_spec, gate_spec

_BLOCKING_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, os, sys, time\n"
    "json.load(sys.stdin)\n"
    "with open(os.environ['GATE_TEST_STARTED'], 'w') as stream:\n"
    "    stream.write('1')\n"
    "deadline = time.time() + 10\n"
    "while not os.path.exists(os.environ['GATE_TEST_RELEASE']):\n"
    "    if time.time() > deadline:\n"
    "        raise SystemExit('release sentinel never appeared')\n"
    "    time.sleep(0.02)\n"
    "print(json.dumps({'status': 'ok'}))\n"
)


def _two_branch_spec(*, request_id: str) -> dict[str, object]:
    """A gate offering ``proceed`` and ``audit`` as two independent branches."""
    spec = custom_gate_spec(request_id=request_id)
    spec["query"] = "proceed OR audit"
    spec["primary_branch"] = ["proceed"]
    spec["options"] = [
        option
        for option in cast("list[dict[str, object]]", spec["options"])
        if option["id"] in {"proceed", "audit"}
    ]
    spec["groups"] = []
    spec["resources"] = [
        resource
        for resource in cast("list[dict[str, object]]", spec["resources"])
        if resource.get("path") in {"commands/proceed", "commands/audit"}
    ]
    return spec


def test_decision_accepted_and_dismissed_while_option_command_still_blocked(
    gate_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance must not wait behind a slow option command.

    This is the regression test for the whole phase: block the *only*
    option command indefinitely, and assert the receipt and notification
    dismissal are already durable while that command is still running --
    before ``response.json`` exists at all.
    """
    started = tmp_path / "started"
    release = tmp_path / "release"
    monkeypatch.setenv("GATE_TEST_STARTED", str(started))
    monkeypatch.setenv("GATE_TEST_RELEASE", str(release))
    result = create_gate(
        gate_spec(request_id="blocked-command", command=_BLOCKING_COMMAND)
    )

    outcome: dict[str, object] = {}

    def _run() -> None:
        try:
            outcome["execution"] = execute_gate_selection(
                result.bundle_path, ["accept"], {}
            )
        except Exception as exc:  # pragma: no cover - surfaced via assertion below
            outcome["error"] = exc

    thread = threading.Thread(target=_run)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not started.exists():
            assert time.monotonic() < deadline, "option command never started"
            time.sleep(0.01)  # sase-test-wait: poll option-command start sentinel

        # The command is now parked, waiting on the release sentinel. Nothing
        # about execution has finished.
        assert not result.response_path.exists()

        receipt_path = result.bundle_path / DECISION_RECEIPT_FILENAME
        deadline = time.monotonic() + 5
        while not receipt_path.is_file():
            assert time.monotonic() < deadline, "decision receipt never appeared"
            time.sleep(0.01)  # sase-test-wait: poll durable receipt write
        receipt = json.loads(receipt_path.read_text())
        assert receipt["selected_option_ids"] == ["accept"]

        deadline = time.monotonic() + 5
        while True:
            [notification] = load_notifications(include_dismissed=True)
            if notification.dismissed:
                break
            assert time.monotonic() < deadline, "notification was never dismissed"
            time.sleep(0.01)  # sase-test-wait: poll notification dismissal state
    finally:
        release.touch()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert "error" not in outcome, outcome.get("error")
    assert outcome["execution"].response["option_results"] == [
        {"id": "accept", "result": {"status": "ok"}}
    ]


def test_identical_resubmission_replays_the_original_receipt(gate_home: Path) -> None:
    result = create_gate(gate_spec(request_id="replay"))

    first = accept_gate_decision(result.bundle_path, ["accept"], {"note": "x"})
    assert first is not None
    assert first.already_accepted is False

    second = accept_gate_decision(result.bundle_path, ["accept"], {"note": "x"})
    assert second is not None
    assert second.already_accepted is True
    assert second.receipt == first.receipt


def test_conflicting_selection_is_rejected_before_any_command_runs(
    gate_home: Path,
) -> None:
    result = create_gate(_two_branch_spec(request_id="conflict-selection"))
    accepted = accept_gate_decision(result.bundle_path, ["proceed"], {})
    assert accepted is not None

    started: list[str] = []
    with pytest.raises(GateError) as rejected:
        execute_gate_selection(
            result.bundle_path,
            ["audit"],
            {},
            on_command_start=lambda _kind, option_id, _label, _argv: started.append(
                option_id
            ),
        )
    assert rejected.value.code == "gate_decision_conflict"
    assert started == [], "a conflicting decision must not run any option command"
    assert not result.response_path.exists()

    # The original decision is untouched and still resolvable.
    replay = accept_gate_decision(result.bundle_path, ["proceed"], {})
    assert replay is not None
    assert replay.already_accepted is True
    assert replay.receipt == accepted.receipt


def test_conflicting_selection_over_running_attempt_is_rejected(
    gate_home: Path,
) -> None:
    result = create_gate(_two_branch_spec(request_id="live-attempt-conflict"))
    accepted = accept_gate_decision(result.bundle_path, ["proceed"], {})
    assert accepted is not None
    acceptance_id = receipt_acceptance_id(accepted.receipt)

    append_journal_event(
        result.bundle_path,
        attempt_id="attempt-live",
        request_hash=str(accepted.receipt["request_hash"]),
        event="attempt_started",
        selected_option_ids=["proceed"],
        input_digests={"proceed": "digest"},
        acceptance_id=acceptance_id,
    )

    with pytest.raises(GateError) as rejected:
        accept_gate_decision(result.bundle_path, ["audit"], {})
    assert rejected.value.code == "gate_decision_conflict"

    receipt = json.loads((result.bundle_path / DECISION_RECEIPT_FILENAME).read_text())
    assert receipt["selected_option_ids"] == ["proceed"]


def test_conflicting_selection_supersedes_after_current_failure(
    gate_home: Path,
) -> None:
    result = create_gate(_two_branch_spec(request_id="failed-attempt-supersede"))
    accepted = accept_gate_decision(result.bundle_path, ["proceed"], {})
    assert accepted is not None
    acceptance_id = receipt_acceptance_id(accepted.receipt)

    append_journal_event(
        result.bundle_path,
        attempt_id="",
        request_hash=str(accepted.receipt["request_hash"]),
        event="attempt_failed",
        stage="command",
        code="feedback_required",
        message="feedback is required",
        outcome_id="outcome-1",
        error_record="errors/outcome-1.json",
        acceptance_id=acceptance_id,
    )

    superseded = accept_gate_decision(result.bundle_path, ["audit"], {})
    assert superseded is not None
    assert superseded.already_accepted is False
    assert superseded.receipt["selected_option_ids"] == ["audit"]
    assert superseded.receipt["acceptance_id"] != acceptance_id


def test_cancel_is_permitted_after_current_failure(gate_home: Path) -> None:
    result = create_gate(gate_spec(request_id="cancel-after-failure"))
    accepted = accept_gate_decision(result.bundle_path, ["accept"], {})
    assert accepted is not None
    acceptance_id = receipt_acceptance_id(accepted.receipt)

    append_journal_event(
        result.bundle_path,
        attempt_id="",
        request_hash=str(accepted.receipt["request_hash"]),
        event="attempt_failed",
        stage="command",
        code="feedback_required",
        message="feedback is required",
        outcome_id="outcome-1",
        error_record="errors/outcome-1.json",
        acceptance_id=acceptance_id,
    )

    cancellation = cancel_gate(result.bundle_path)
    assert cancellation["reason"] == "requester_cancelled"


def test_conflicting_selection_supersedes_after_dead_process_owner(
    gate_home: Path,
) -> None:
    result = create_gate(_two_branch_spec(request_id="dead-owner-supersede"))
    accepted = accept_gate_decision(result.bundle_path, ["proceed"], {})
    assert accepted is not None

    receipt_path = result.bundle_path / DECISION_RECEIPT_FILENAME
    receipt = dict(accepted.receipt)
    receipt["execution_owner"] = {
        "kind": "process",
        "host": socket.gethostname(),
        "pid": 999_999_999,
        "identity_token": "previous-boot:1",
    }
    atomic_write_json(receipt_path, receipt)

    superseded = accept_gate_decision(result.bundle_path, ["audit"], {})
    assert superseded is not None
    assert superseded.already_accepted is False
    assert superseded.receipt["selected_option_ids"] == ["audit"]


def test_poll_gate_records_dead_owner_as_failed_execution(gate_home: Path) -> None:
    result = create_gate(gate_spec(request_id="dead-owner-poll"))
    accepted = accept_gate_decision(result.bundle_path, ["accept"], {})
    assert accepted is not None

    receipt_path = result.bundle_path / DECISION_RECEIPT_FILENAME
    receipt = dict(accepted.receipt)
    receipt["execution_owner"] = {
        "kind": "process",
        "host": socket.gethostname(),
        "pid": 999_999_999,
        "identity_token": "previous-boot:1",
    }
    atomic_write_json(receipt_path, receipt)

    polled = poll_gate(result.bundle_path)

    assert polled is not None
    assert polled.status == "failed"
    assert polled.failure is not None
    assert polled.failure["code"] == "execution_owner_lost"
    assert polled.failure["stage"] == "command"
    failures = [
        notification
        for notification in load_notifications()
        if notification.action == GATE_EXECUTION_FAILED_ACTION
    ]
    assert len(failures) == 1
    assert failures[0].action_data["request_id"] == "dead-owner-poll"


def test_racing_conflicting_submissions_exactly_one_wins(gate_home: Path) -> None:
    result = create_gate(_two_branch_spec(request_id="race"))
    start = threading.Barrier(2)
    lock = threading.Lock()
    outcomes: list[tuple[str, str, object]] = []

    def _submit(option_id: str) -> None:
        start.wait(timeout=5)
        try:
            accepted = accept_gate_decision(result.bundle_path, [option_id], {})
            with lock:
                outcomes.append(("ok", option_id, accepted))
        except GateError as exc:
            with lock:
                outcomes.append(("error", option_id, exc.code))

    threads = [
        threading.Thread(target=_submit, args=(option_id,))
        for option_id in ("proceed", "audit")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(outcomes) == 2
    wins = [entry for entry in outcomes if entry[0] == "ok"]
    losses = [entry for entry in outcomes if entry[0] == "error"]
    assert len(wins) == 1, outcomes
    assert len(losses) == 1, outcomes
    assert losses[0][2] == "gate_decision_conflict"

    receipt = json.loads((result.bundle_path / DECISION_RECEIPT_FILENAME).read_text())
    assert receipt["selected_option_ids"] == [wins[0][1]]


def test_cancel_is_refused_once_a_decision_is_accepted(gate_home: Path) -> None:
    result = create_gate(gate_spec(request_id="cancel-after-accept"))
    accept_gate_decision(result.bundle_path, ["accept"], {})

    with pytest.raises(GateError) as rejected:
        cancel_gate(result.bundle_path)
    assert rejected.value.code == "already_answered"


def test_cancel_still_succeeds_before_any_decision_is_accepted(
    gate_home: Path,
) -> None:
    result = create_gate(gate_spec(request_id="cancel-before-accept"))

    cancellation = cancel_gate(result.bundle_path)
    assert cancellation["reason"] == "requester_cancelled"

    with pytest.raises(GateError) as rejected:
        accept_gate_decision(result.bundle_path, ["accept"], {})
    assert rejected.value.code == "gate_cancelled"
