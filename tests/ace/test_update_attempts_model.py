"""Tests for the pure update-attempt journal reducers and bounds."""

from __future__ import annotations

from sase.ace._update_attempts_model import (
    INTERRUPTED_ERROR,
    MAX_ERROR_CHARS,
    MAX_IN_FLIGHT_ATTEMPTS,
    MAX_OUTPUT_BYTES,
    MAX_OUTPUT_LINES,
    UpdateAttempt,
    UpdateAttemptOwner,
    UpdateStage,
    attempts_record_from_json,
    attempts_record_to_json,
    _bound_error_text,
    _bound_output_tail,
    empty_attempts_record,
    new_update_attempt,
    reduce_dismiss,
    reduce_reconcile,
    reduce_settle,
    reduce_start,
)

_OTHER_OWNER = UpdateAttemptOwner(pid=4242, identity="boot:1", instance_id="other")
_DEAD_OWNER = UpdateAttemptOwner(pid=4243, identity="boot:2", instance_id="dead")


def _attempt(
    attempt_id: str = "a1",
    started_at: float = 1000.0,
    label: str = "update everything",
    proc_type: str = "comprehensive-update",
) -> UpdateAttempt:
    stage: UpdateStage = "plan" if proc_type == "update-preview" else "apply"
    return UpdateAttempt(
        attempt_id=attempt_id,
        label=label,
        proc_type=proc_type,
        stage=stage,
        started_at=started_at,
    )


def test_new_attempt_stage_mapping() -> None:
    plan = new_update_attempt(label="plan update", proc_type="update-preview")
    apply = new_update_attempt(label="update everything", proc_type="x")
    assert plan.stage == "plan"
    assert apply.stage == "apply"
    assert plan.attempt_id != apply.attempt_id


def test_start_adds_and_replaces_marker() -> None:
    record = empty_attempts_record()
    attempt = _attempt()
    updated, changed = reduce_start(record, attempt, _OTHER_OWNER, now=1001.0)
    assert changed
    assert updated.revision == 1
    assert [m.attempt_id for m in updated.in_flight] == ["a1"]
    assert updated.in_flight[0].owner == _OTHER_OWNER

    other_owner = UpdateAttemptOwner(pid=1, identity="b:3", instance_id="i3")
    replaced, changed = reduce_start(updated, attempt, other_owner, now=1002.0)
    assert changed
    assert replaced.revision == 2
    assert [m.attempt_id for m in replaced.in_flight] == ["a1"]
    assert replaced.in_flight[0].owner == other_owner

    assert reduce_start(replaced, attempt, other_owner, now=1003.0) == (replaced, False)


def test_start_caps_in_flight_dropping_oldest() -> None:
    record = empty_attempts_record()
    for i in range(MAX_IN_FLIGHT_ATTEMPTS + 4):
        attempt = _attempt(attempt_id=f"a{i}", started_at=1000.0 + i)
        record, _ = reduce_start(record, attempt, _OTHER_OWNER, now=2000.0)
    assert [m.attempt_id for m in record.in_flight] == [
        f"a{i}" for i in range(4, MAX_IN_FLIGHT_ATTEMPTS + 4)
    ]


def test_sequential_fail_then_success_clears() -> None:
    record = empty_attempts_record()
    failed, _ = reduce_settle(
        record,
        _attempt(started_at=1000.0),
        success=False,
        error="boom",
        output="out",
        now=1010.0,
    )
    assert failed.failure is not None
    assert failed.failure.error == "boom"
    assert failed.revision == 1

    cleared, changed = reduce_settle(
        failed,
        _attempt(attempt_id="a2", started_at=1020.0),
        success=True,
        error=None,
        output=None,
        now=1030.0,
    )
    assert changed
    assert cleared.failure is None


def test_earlier_started_success_keeps_failure() -> None:
    record = empty_attempts_record()
    failed, _ = reduce_settle(
        record,
        _attempt(attempt_id="new", started_at=2000.0),
        success=False,
        error="boom",
        output=None,
        now=2010.0,
    )
    kept, changed = reduce_settle(
        failed,
        _attempt(attempt_id="old", started_at=1000.0),
        success=True,
        error=None,
        output=None,
        now=2020.0,
    )
    assert kept.failure is not None
    assert kept.failure.attempt_id == "new"
    assert changed  # last_success_started_at still advanced
    assert kept.last_success_started_at == 1000.0


def test_newer_failure_replaces_older() -> None:
    record = empty_attempts_record()
    first, _ = reduce_settle(
        record,
        _attempt(attempt_id="a1", started_at=1000.0),
        success=False,
        error="first",
        output=None,
        now=1010.0,
    )
    second, changed = reduce_settle(
        first,
        _attempt(attempt_id="a2", started_at=1020.0),
        success=False,
        error="second",
        output=None,
        now=1030.0,
    )
    assert changed
    assert second.failure is not None
    assert second.failure.attempt_id == "a2"
    assert second.failure.error == "second"


def test_settle_without_marker_still_records() -> None:
    record = empty_attempts_record()
    updated, changed = reduce_settle(
        record,
        _attempt(),
        success=False,
        error="boom",
        output=None,
        now=1010.0,
    )
    assert changed
    assert updated.in_flight == ()
    assert updated.failure is not None


def test_dismiss_matches_attempt_id_only() -> None:
    record = empty_attempts_record()
    failed, _ = reduce_settle(
        record, _attempt(), success=False, error="boom", output=None, now=1010.0
    )
    stale, changed = reduce_dismiss(failed, "other-id", now=1020.0)
    assert (stale, changed) == (failed, False)

    cleared, changed = reduce_dismiss(failed, "a1", now=1020.0)
    assert changed
    assert cleared.failure is None


def test_error_bound_takes_first_non_empty_line() -> None:
    assert _bound_error_text("\n  \nboom\nsecond") == "boom"
    assert _bound_error_text(None) == ""
    assert _bound_error_text("   \n\t") == ""


def test_error_bound_caps_with_ellipsis() -> None:
    long_error = "x" * (MAX_ERROR_CHARS + 50)
    bounded = _bound_error_text(long_error)
    assert len(bounded) == MAX_ERROR_CHARS
    assert bounded.endswith("…")
    assert _bound_error_text("y" * MAX_ERROR_CHARS) == "y" * MAX_ERROR_CHARS


def test_output_tail_keeps_last_lines_within_budget() -> None:
    output = "\n".join(f"line {i}" for i in range(MAX_OUTPUT_LINES + 50))
    tail = _bound_output_tail(output)
    lines = tail.splitlines()
    assert len(lines) == MAX_OUTPUT_LINES
    assert lines[0] == f"line {50}"
    assert len(tail.encode("utf-8")) <= MAX_OUTPUT_BYTES


def test_output_tail_trims_on_line_boundary() -> None:
    output = "\n".join(f"line {i} " + "x" * 100 for i in range(500))
    tail = _bound_output_tail(output)
    assert len(tail.encode("utf-8")) <= MAX_OUTPUT_BYTES
    assert tail.splitlines()[0].startswith("line ")
    assert _bound_output_tail(None) == ""


def test_revision_bumps_only_on_change() -> None:
    record = empty_attempts_record()
    assert record.revision == 0
    started, _ = reduce_start(record, _attempt(), _OTHER_OWNER, now=1001.0)
    assert started.revision == 1
    assert reduce_dismiss(started, "missing", now=1002.0)[0].revision == 1
    assert reduce_reconcile(started, lambda owner: True, now=1003.0) == (started, False)


def test_reconcile_dead_owner_becomes_interrupted() -> None:
    record = empty_attempts_record()
    started, _ = reduce_start(record, _attempt(), _DEAD_OWNER, now=1001.0)
    reconciled, changed = reduce_reconcile(started, lambda owner: False, now=1100.0)
    assert changed
    assert reconciled.in_flight == ()
    assert reconciled.failure is not None
    assert reconciled.failure.interrupted is True
    assert reconciled.failure.finished_at == 1100.0
    assert reconciled.failure.error == INTERRUPTED_ERROR


def test_reconcile_keeps_live_and_own_markers() -> None:
    record = empty_attempts_record()
    live_attempt = _attempt(attempt_id="live", started_at=1000.0)
    record, _ = reduce_start(record, live_attempt, _OTHER_OWNER, now=1001.0)
    record, _ = reduce_start(
        record, _attempt(attempt_id="dead", started_at=1000.0), _DEAD_OWNER, now=1001.0
    )
    reconciled, changed = reduce_reconcile(
        record, lambda owner: owner == _OTHER_OWNER, now=1100.0
    )
    assert changed
    assert [m.attempt_id for m in reconciled.in_flight] == ["live"]
    assert reconciled.failure is not None
    assert reconciled.failure.attempt_id == "dead"


def test_reconcile_later_success_suppresses_interrupted() -> None:
    record = empty_attempts_record()
    record, _ = reduce_settle(
        record,
        _attempt(attempt_id="ok", started_at=2000.0),
        success=True,
        error=None,
        output=None,
        now=2010.0,
    )
    record, _ = reduce_start(
        record, _attempt(attempt_id="stale", started_at=1000.0), _DEAD_OWNER, now=2020.0
    )
    reconciled, changed = reduce_reconcile(record, lambda owner: False, now=2100.0)
    assert changed  # the dead marker is still dropped
    assert reconciled.in_flight == ()
    assert reconciled.failure is None


def test_record_json_round_trip_with_unknown_keys() -> None:
    record = empty_attempts_record()
    record, _ = reduce_start(record, _attempt(), _OTHER_OWNER, now=1001.0)
    record, _ = reduce_start(
        record, _attempt(attempt_id="a2", started_at=1002.0), _OTHER_OWNER, now=1003.0
    )
    record, _ = reduce_settle(
        record, _attempt(), success=False, error="boom", output="out", now=1010.0
    )
    payload = attempts_record_to_json(record)
    payload["unknown_future_key"] = {"nested": True}
    payload["in_flight"][0]["unknown"] = 1
    assert payload["failure"] is not None
    payload["failure"]["unknown"] = 2
    assert attempts_record_from_json(payload) == record


def test_record_json_rejects_wrong_types() -> None:
    assert attempts_record_from_json(None) is None
    assert attempts_record_from_json([]) is None
    assert attempts_record_from_json({"schema": 1}) is None
    assert attempts_record_from_json({"schema": "1", "revision": 0}) is None
    record = empty_attempts_record()
    payload = attempts_record_to_json(record)
    payload["revision"] = "7"
    assert attempts_record_from_json(payload) is None
    payload = attempts_record_to_json(record)
    payload["in_flight"] = [{"attempt_id": 1}]
    assert attempts_record_from_json(payload) is None
