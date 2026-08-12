"""Shared agent status-bucket vocabulary tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sase.ace.tui.models._agent_clan import aggregate_clan_status
from sase.agent.status_buckets import (
    PENDING_PLAN_REVIEW_STATUSES,
    _BUCKET_REPRESENTATIVE_STATUS,
    aggregate_agent_group_bucket,
    aggregate_agent_group_effective_status,
    aggregate_agent_group_status,
    agent_is_asking,
    agent_status_bucket,
    is_pending_plan_review_status,
    pending_plan_status_for_tier,
    runner_slot_display_status,
    status_bucket_for_values,
)


@dataclass
class _AgentStatusRow:
    status: str
    retried_as_timestamp: str | None = None
    status_bucket: str | None = None


@pytest.mark.parametrize(
    ("tier", "expected"),
    [("tale", "TALE"), (" TALE ", "TALE"), ("epic", "EPIC"), (None, "PLAN")],
)
def test_pending_plan_status_for_tier(tier: str | None, expected: str) -> None:
    assert pending_plan_status_for_tier(tier) == expected


@pytest.mark.parametrize("status", PENDING_PLAN_REVIEW_STATUSES)
def test_pending_plan_review_statuses_share_semantics(status: str) -> None:
    assert is_pending_plan_review_status(status)
    assert agent_is_asking(status)
    assert status_bucket_for_values(status) == "Stopped"


def test_non_pending_status_is_not_pending_plan_review() -> None:
    assert not is_pending_plan_review_status("PLAN APPROVED")
    assert not is_pending_plan_review_status(None)


def test_agent_status_bucket_uses_valid_override_for_unknown_status() -> None:
    row = _AgentStatusRow(status="MONITORED", status_bucket="Done")

    assert agent_status_bucket(row) == "Done"


def test_agent_status_bucket_ignores_unknown_override() -> None:
    row = _AgentStatusRow(status="FAILED", status_bucket="Bogus")

    assert agent_status_bucket(row) == "Failed"


@pytest.mark.parametrize("status", ["WAITING", "QUEUED"])
def test_live_runner_slot_waiter_displays_queued(status: str) -> None:
    assert runner_slot_display_status(status, slot_queued=True) == "QUEUED"


def test_wait_without_live_slot_request_displays_waiting() -> None:
    assert runner_slot_display_status("QUEUED", slot_queued=False) == "WAITING"


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], None),
        (["WAITING"], "WAITING"),
        (["QUEUED"], "QUEUED"),
        (["QUEUED", "WAITING"], "QUEUED"),
        (["QUEUED", "WAITING", "DONE"], "QUEUED"),
        (["QUEUED", "DONE"], "QUEUED"),
        (["WAITING", "DONE"], "WAITING"),
        (["DONE", "STOPPED", "PLAN REJECTED"], "DONE"),
        (["UNKNOWN"], "RUNNING"),
        (["QUEUED", "WAITING", "QUESTION"], "QUESTION"),
        (["QUEUED", "WAITING", "WAITING INPUT"], "QUESTION"),
        (["QUEUED", "WAITING", "PLAN"], "PLAN"),
        (["QUEUED", "WAITING", "TALE"], "TALE"),
        (["QUEUED", "WAITING", "EPIC"], "EPIC"),
        (["QUEUED", "WAITING", "FAILED"], "FAILED"),
        (["QUEUED", "WAITING", "KILLED"], "FAILED"),
        (["QUEUED", "WAITING", "RUNNING"], "RUNNING"),
        (["QUEUED", "WAITING", "STARTING"], "RUNNING"),
    ],
)
def test_aggregate_agent_group_status_priority(
    statuses: list[str],
    expected: str | None,
) -> None:
    assert aggregate_agent_group_status(statuses) == expected
    assert aggregate_clan_status(statuses) == expected


def test_aggregate_agent_group_bucket_honors_effective_override() -> None:
    assert (
        aggregate_agent_group_bucket((("TALE APPROVED", "Done"), ("TALE DONE", "Done")))
        == "Done"
    )


def test_aggregate_agent_group_effective_status_honors_override() -> None:
    assert aggregate_agent_group_effective_status((("MONITORED", "Done"),)) == "DONE"


@pytest.mark.parametrize(
    "statuses",
    [
        ("WAITING", "DONE"),
        ("QUEUED", "WAITING", "DONE"),
        ("STARTING", "DONE"),
        ("PLAN", "WAITING"),
        ("TALE", "EPIC"),
        ("FAILED", "RUNNING"),
        ("UNKNOWN",),
    ],
)
def test_aggregate_agent_group_bucket_matches_status_aggregate_without_overrides(
    statuses: tuple[str, ...],
) -> None:
    aggregate_status = aggregate_agent_group_status(statuses)
    assert aggregate_status is not None
    assert aggregate_agent_group_bucket(
        (status, status_bucket_for_values(status)) for status in statuses
    ) == status_bucket_for_values(aggregate_status)


def test_aggregate_agent_group_bucket_empty_input_returns_none() -> None:
    assert aggregate_agent_group_bucket(()) is None


@pytest.mark.parametrize(
    ("status", "expected"),
    [("KILLED", "Failed"), ("WAITING INPUT", "Stopped")],
)
def test_aggregate_agent_group_bucket_preserves_special_status_paths(
    status: str,
    expected: str,
) -> None:
    assert (
        aggregate_agent_group_bucket(((status, status_bucket_for_values(status)),))
        == expected
    )


def test_bucket_representative_statuses_round_trip() -> None:
    assert all(
        status_bucket_for_values(status) == bucket
        for bucket, status in _BUCKET_REPRESENTATIVE_STATUS.items()
    )
