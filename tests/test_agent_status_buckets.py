"""Shared agent status-bucket vocabulary tests."""

from __future__ import annotations

import pytest

from sase.agent.status_buckets import (
    PENDING_PLAN_REVIEW_STATUSES,
    agent_is_asking,
    is_pending_plan_review_status,
    pending_plan_status_for_tier,
    status_bucket_for_values,
)


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
