"""Tests for the reserved RUNNING-field claim-label vocabulary."""

import pytest

from sase.running_field import (
    OPERATIONAL_LEASE_CLAIM_PREFIX,
    is_operational_lease_claim_workflow,
    operational_lease_claim_workflow,
)


def test_wraps_caller_workflow_in_reserved_label() -> None:
    """A caller's workflow identity becomes a ``lease(...)`` claim label."""
    assert (
        operational_lease_claim_workflow("chop:bead_claim_checks")
        == "lease(chop:bead_claim_checks)"
    )
    assert operational_lease_claim_workflow("bead_claim") == "lease(bead_claim)"


def test_wrapping_is_idempotent() -> None:
    """A normalized label fed back in is never double-wrapped."""
    once = operational_lease_claim_workflow("plan-archive")
    assert operational_lease_claim_workflow(once) == once


def test_reserved_label_contains_no_whitespace() -> None:
    """RUNNING lines parse the workflow column as a whitespace-free token."""
    label = operational_lease_claim_workflow("chop:external_issue_mirror")
    assert label.startswith(OPERATIONAL_LEASE_CLAIM_PREFIX)
    assert not any(char.isspace() for char in label)


@pytest.mark.parametrize(
    "workflow",
    [
        "lease(chop:bead_claim_checks)",
        "lease(bead_claim)",
        "lease(plan-archive)",
    ],
)
def test_recognizes_operational_lease_labels(workflow: str) -> None:
    assert is_operational_lease_claim_workflow(workflow) is True


@pytest.mark.parametrize(
    "workflow",
    [
        None,
        "",
        "ace(run)-260816_112109",
        "workflow(refresh_cl_desc)",
        "axe(hooks)-1",
        "ace-monitor",
        "chop:bead_claim_checks",
        "lease(unterminated",
    ],
)
def test_rejects_non_lease_labels(workflow: str | None) -> None:
    assert is_operational_lease_claim_workflow(workflow) is False
