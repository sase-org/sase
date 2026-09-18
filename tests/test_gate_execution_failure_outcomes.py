"""Durable, redacted failure outcomes for gate execution (bead sase-zr.7.1.1.2)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.notification_gates.adapters import GateAdapter
from sase.notification_gates.decision import read_current_receipt, receipt_acceptance_id
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.failure_outcome import with_follow_up_stage_tracking
from sase.notification_gates.journal import (
    append_journal_event,
    incomplete_attempt,
    read_journal_records,
)
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from tests._notification_gates_fixtures import custom_gate_spec, gate_spec
from tests.test_bead.task_gate_test_helpers import task_triage_spec


def _events(bundle_path: Path) -> list[str]:
    return [str(record["event"]) for record in read_journal_records(bundle_path)]


def _failures(bundle_path: Path) -> list[dict[str, Any]]:
    return [
        record
        for record in read_journal_records(bundle_path)
        if record["event"] == "attempt_failed"
    ]


def test_terminal_prepare_failure_then_resume_retries_only_terminal_prepare(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = create_gate(gate_spec(request_id="terminal-prepare-failure"))
    calls = {"n": 0}
    original = GateAdapter.prepare_terminal_response

    def flaky(
        self: GateAdapter, *, bundle_path: Path, response: dict[str, Any]
    ) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("archive unavailable")
        original(self, bundle_path=bundle_path, response=response)

    monkeypatch.setattr(GateAdapter, "prepare_terminal_response", flaky)

    with pytest.raises(GateError) as failed:
        execute_gate_selection(created.bundle_path, ["accept"], {"reviewed": True})
    assert failed.value.code == "terminal_prepare_failed"
    assert not created.response_path.exists()

    events = _events(created.bundle_path)
    assert events == [
        "attempt_started",
        "option_completed",
        "stage_started",
        "attempt_failed",
    ]
    [failure] = _failures(created.bundle_path)
    assert failure["stage"] == "terminal_prepare"
    assert failure["code"] == "terminal_prepare_failed"
    assert failure["attempt_id"]
    assert failure["outcome_id"]
    assert (created.bundle_path / failure["error_record"]).is_file()

    receipt = read_current_receipt(created.bundle_path)
    assert receipt_acceptance_id(receipt) == failure["acceptance_id"]

    with pytest.raises(GateError) as partial:
        execute_gate_selection(created.bundle_path, ["accept"], {"reviewed": True})
    assert partial.value.code == "partial_attempt"
    assert "all options completed; terminal preparation failed" in str(partial.value)
    assert _events(created.bundle_path) == events, (
        "a rejected resubmission records nothing new"
    )

    execution = execute_gate_selection(
        created.bundle_path, ["accept"], {"reviewed": True}, retry="resume"
    )
    assert calls["n"] == 2
    assert execution.already_completed is False
    assert created.response_path.is_file()

    events_after = _events(created.bundle_path)
    assert events_after.count("option_completed") == 1, (
        "the completed option never re-ran"
    )
    assert "attempt_resumed" in events_after
    assert events_after.index("attempt_completed") > events_after.index(
        "attempt_failed"
    )
    assert events_after[-1] == "stage_completed"


def test_side_effect_failure_is_recorded_after_attempt_completed_and_resume_reruns_only_it(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = create_gate(gate_spec(request_id="side-effect-failure"))
    calls = {"n": 0}

    def flaky(
        self: GateAdapter,
        *,
        bundle_path: Path,
        response: dict[str, Any],
        epic_launch_origin: object = None,
    ) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("side effect boom")

    monkeypatch.setattr(GateAdapter, "apply_side_effects", flaky)

    with pytest.raises(GateError) as failed:
        execute_gate_selection(created.bundle_path, ["accept"], {"reviewed": True})
    assert failed.value.code == "side_effect_failed"
    assert created.response_path.is_file(), (
        "the response is already durable when side effects fail"
    )

    events = _events(created.bundle_path)
    assert events.index("attempt_completed") < events.index("attempt_failed")
    [failure] = _failures(created.bundle_path)
    assert failure["stage"] == "side_effects"

    # A plain identical answer (no retry) stays the idempotent short-circuit
    # and never re-attempts the failed side effect.
    plain = execute_gate_selection(created.bundle_path, ["accept"], {"reviewed": True})
    assert plain.already_completed is True
    assert calls["n"] == 1

    resumed = execute_gate_selection(
        created.bundle_path, ["accept"], {"reviewed": True}, retry="resume"
    )
    assert resumed.already_completed is True
    assert calls["n"] == 2

    events_after = _events(created.bundle_path)
    assert events_after[-1] == "stage_completed"
    # One terminal_prepare stage_started, plus one per side_effects attempt.
    assert events_after.count("stage_started") == 3


def test_command_failure_records_a_fixed_summary_with_no_stdout_or_secret(
    gate_home: Path,
) -> None:
    fail_and_echo = (
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "value = json.load(sys.stdin)\n"
        "sys.stderr.write('leaking ' + value['token'] + '\\n')\n"
        "sys.exit(3)\n"
    )
    spec: dict[str, Any] = custom_gate_spec(request_id="command-failure")
    spec["options"][0].pop("input_schema", None)
    spec["options"][0]["inputs"] = [
        {
            "id": "token",
            "label": "Token",
            "type": "text",
            "required": True,
            "secret": True,
        },
    ]
    spec["resources"][0]["content"] = fail_and_echo
    result = create_gate(spec)

    with pytest.raises(GateError) as failed:
        execute_gate_selection(result.bundle_path, ["proceed"], {"token": "topsecret"})
    assert failed.value.code == "command_failed"

    [failure] = _failures(result.bundle_path)
    assert failure["stage"] == "command"
    assert failure["code"] == "command_failed"
    assert "exit status 3" in failure["message"]
    assert "topsecret" not in failure["message"]
    assert "leaking" not in failure["message"]

    error_records = [
        json.loads(path.read_text())
        for path in (result.bundle_path / "errors").glob("*.json")
    ]
    # errors/*.json (the ``d`` debug record) is untouched by this phase: it
    # still captures full context, including the leaked stderr line.
    assert any("topsecret" in (record.get("stderr") or "") for record in error_records)


def test_pre_attempt_revalidation_failure_uses_command_stage_and_synthetic_attempt_id(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = create_gate(gate_spec(request_id="pre-attempt-failure"))

    def boom(selected: object, feedback: object) -> None:
        raise GateError("feedback_required", "accept", "feedback is required")

    monkeypatch.setattr("sase.notification_gates.executor.normalize_feedback", boom)

    with pytest.raises(GateError) as exc:
        execute_gate_selection(created.bundle_path, ["accept"], {"reviewed": True})
    assert exc.value.code == "feedback_required"

    [failure] = _failures(created.bundle_path)
    assert failure["attempt_id"] == "pre_attempt"
    assert failure["stage"] == "command"
    assert failure["code"] == "feedback_required"


def test_keyboard_interrupt_is_recorded_as_execution_interrupted_and_reraised(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = create_gate(gate_spec(request_id="ctrl-c"))

    def boom(selected: object, feedback: object) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr("sase.notification_gates.executor.normalize_feedback", boom)

    with pytest.raises(KeyboardInterrupt):
        execute_gate_selection(created.bundle_path, ["accept"], {"reviewed": True})

    [failure] = _failures(created.bundle_path)
    assert failure["code"] == "execution_interrupted"


def test_negotiation_errors_never_record_a_failure_outcome(gate_home: Path) -> None:
    created = create_gate(gate_spec(request_id="no-partial"))

    with pytest.raises(GateError) as exc:
        execute_gate_selection(
            created.bundle_path, ["accept"], {"reviewed": True}, retry="resume"
        )
    assert exc.value.code == "no_partial_attempt"
    assert read_journal_records(created.bundle_path) == ()


def test_incomplete_attempt_treats_a_legacy_early_attempt_completed_as_still_open(
    tmp_path: Path,
) -> None:
    bundle = tmp_path
    append_journal_event(
        bundle,
        attempt_id="a1",
        request_hash="h",
        event="attempt_started",
        selected_option_ids=["accept"],
        input_digests={"accept": "d"},
    )
    append_journal_event(
        bundle,
        attempt_id="a1",
        request_hash="h",
        event="option_completed",
        option_id="accept",
        input_digest="d",
        result_digest="rd",
        result={"status": "ok"},
    )
    # Legacy behavior: attempt_completed was journaled before archive ran.
    append_journal_event(
        bundle, attempt_id="a1", request_hash="h", event="attempt_completed"
    )

    assert incomplete_attempt(bundle, response_exists=True) is None
    pending = incomplete_attempt(bundle, response_exists=False)
    assert pending is not None
    assert pending.completed_option_ids == ("accept",)


def test_side_effects_resume_skips_a_launch_response_json_already_recorded(
    gate_home: Path,
) -> None:
    gate = create_gate(task_triage_spec(request_id="task-triage-resume-guard"))
    task = SimpleNamespace(proc_id="task-bg-1")

    with patch(
        "sase.bead.task_launch.submit_task_launch_task", return_value=task
    ) as submit:
        execution = execute_gate_selection(
            gate.bundle_path,
            ["launch"],
            {},
            feedback="Keep the compatibility shim.",
            source="tui",
        )
    assert execution.response["task_launch_task_id"] == "task-bg-1"
    assert submit.call_count == 1

    # Simulate a side-effects failure recorded on some other launch attempt
    # after this one durably recorded its launch id (e.g. a notification
    # dispatch failure past the launch itself).
    receipt = read_current_receipt(gate.bundle_path)
    append_journal_event(
        gate.bundle_path,
        attempt_id="side-effects-attempt",
        request_hash="",
        event="attempt_failed",
        stage="side_effects",
        code="side_effect_failed",
        message="simulated failure after the launch already recorded",
        outcome_id="sim-1",
        error_record="errors/sim.json",
        acceptance_id=receipt_acceptance_id(receipt),
    )

    with patch(
        "sase.bead.task_launch.submit_task_launch_task", return_value=task
    ) as submit_again:
        resumed = execute_gate_selection(
            gate.bundle_path,
            ["launch"],
            {},
            feedback="Keep the compatibility shim.",
            source="tui",
            retry="resume",
        )
    assert submit_again.call_count == 0, "a recorded launch id must never be relaunched"
    assert resumed.already_completed is True
    assert _events(gate.bundle_path)[-1] == "stage_completed"


def test_with_follow_up_stage_tracking_records_success_and_failure(
    tmp_path: Path,
) -> None:
    bundle = tmp_path

    result = with_follow_up_stage_tracking(
        bundle, acceptance_id="acc-1", source="cli", run=lambda: "settled"
    )
    assert result == "settled"
    assert _events(bundle) == ["stage_started", "stage_completed"]
    assert all(
        record["stage"] == "follow_up" for record in read_journal_records(bundle)
    )

    def boom() -> None:
        raise RuntimeError("shell settle exploded")

    with pytest.raises(RuntimeError):
        with_follow_up_stage_tracking(
            bundle, acceptance_id="acc-1", source="cli", run=boom
        )

    events = _events(bundle)
    assert events[-1] == "attempt_failed"
    [failure] = _failures(bundle)
    assert failure["stage"] == "follow_up"
    assert failure["code"] == "adapter_rejected"
    assert len(list((bundle / "errors").glob("*.json"))) == 1
