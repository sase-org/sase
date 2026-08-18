"""Tests for the shared task-bead triage suppression and staleness predicates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, UTC
from types import MappingProxyType
from typing import Any

import pytest

from sase.bead.model import (
    FlagRecord,
    Issue,
    IssueType,
    SnoozeRecord,
    Status,
    TaskPlusOneEvidence,
)
from sase.bead.task_triage_policy import (
    effective_min_plus_ones,
    stale_task_bead,
    task_gate_suppressed,
)
from sase.task_types._models import (
    TaskTypeProvenance,
    TaskTypeRecord,
    TaskTypeRegistry,
)


def _task_type_record(slug: str, *, min_plus_ones: int | None) -> TaskTypeRecord:
    spec: dict[str, Any] = {"task_type": slug, "label": slug}
    if min_plus_ones is not None:
        spec["triage"] = {"min_plus_ones": min_plus_ones}
    return TaskTypeRecord(
        task_type=slug,
        spec=MappingProxyType(spec),
        digest="a" * 64,
        provenance=TaskTypeProvenance(
            source="builtin", name="sase", package="sase", version="1.0.0", builtin=True
        ),
    )


def _registry(*records: TaskTypeRecord) -> TaskTypeRegistry:
    return TaskTypeRegistry(records=records, diagnostics=())


def _make_task(
    *,
    status: Status = Status.READY,
    plus_ones: int = 0,
    created_at: str = "2026-08-01T09:14:02-04:00",
    task_type: str = "",
) -> Issue:
    issue = Issue(
        id="sase-task.1",
        title="Follow up on cache invalidation",
        status=status,
        issue_type=IssueType.TASK,
        created_at=created_at,
        task_type=task_type,
    )
    issue.plus_one_evidence = [
        # `plus_one_count` is `len(plus_one_evidence)`; the field contents
        # don't matter to these predicates, only the count.
        TaskPlusOneEvidence(
            timestamp="2026-08-02T00:00:00-04:00",
            reporter=f"reporter-{i}",
            note="corroborated",
        )
        for i in range(plus_ones)
    ]
    if status == Status.SNOOZED:
        issue.snooze = SnoozeRecord(
            until="2099-01-01T00:00:00-04:00",
            snoozed_at="2026-08-01T00:00:00-04:00",
            snoozed_by="bryan",
            reason="waiting",
        )
    return issue


def _make_due_flag() -> Issue:
    return Issue(
        id="sase-flag.1",
        title="Remove the prettier_enabled flag",
        status=Status.OPEN,
        issue_type=IssueType.FLAG,
        created_at="2026-08-01T09:14:02-04:00",
        flag=FlagRecord(
            key="prettier_enabled",
            remove_by_date="2026-01-01",
            remove_by_release="0.1.0",
        ),
    )


def test_task_gate_suppressed_true_below_bar() -> None:
    issue = _make_task(plus_ones=0)
    assert task_gate_suppressed(issue, min_plus_ones=1) is True


def test_task_gate_suppressed_false_at_bar() -> None:
    issue = _make_task(plus_ones=1)
    assert task_gate_suppressed(issue, min_plus_ones=1) is False


def test_task_gate_suppressed_false_above_bar() -> None:
    issue = _make_task(plus_ones=2)
    assert task_gate_suppressed(issue, min_plus_ones=1) is False


@pytest.mark.parametrize("plus_ones", [0, 1, 5])
def test_task_gate_suppressed_always_false_when_bar_is_zero(plus_ones: int) -> None:
    issue = _make_task(plus_ones=plus_ones)
    assert task_gate_suppressed(issue, min_plus_ones=0) is False


def test_task_gate_suppressed_false_for_snoozed_task() -> None:
    issue = _make_task(status=Status.SNOOZED, plus_ones=0)
    assert task_gate_suppressed(issue, min_plus_ones=1) is False


def test_task_gate_suppressed_false_for_open_task() -> None:
    issue = _make_task(status=Status.OPEN, plus_ones=0)
    assert task_gate_suppressed(issue, min_plus_ones=1) is False


def test_task_gate_suppressed_false_for_due_flag() -> None:
    issue = _make_due_flag()
    assert task_gate_suppressed(issue, min_plus_ones=1) is False


def test_stale_task_bead_true_at_exactly_stale_after_days() -> None:
    now = datetime(2026, 8, 17, 9, 14, 2, tzinfo=timezone(-timedelta(hours=4)))
    issue = _make_task(plus_ones=0, created_at="2026-08-10T09:14:02-04:00")

    assert stale_task_bead(issue, min_plus_ones=1, stale_after_days=7, now=now) is True


def test_stale_task_bead_false_one_second_short_of_stale_after_days() -> None:
    now = datetime(2026, 8, 17, 9, 14, 1, tzinfo=timezone(-timedelta(hours=4)))
    issue = _make_task(plus_ones=0, created_at="2026-08-10T09:14:02-04:00")

    assert stale_task_bead(issue, min_plus_ones=1, stale_after_days=7, now=now) is False


def test_stale_task_bead_false_when_not_suppressed() -> None:
    now = datetime(2026, 8, 17, tzinfo=UTC)
    issue = _make_task(plus_ones=1, created_at="2026-01-01T00:00:00-04:00")

    assert stale_task_bead(issue, min_plus_ones=1, stale_after_days=7, now=now) is False


@pytest.mark.parametrize("created_at", ["", "not-a-date"])
def test_stale_task_bead_false_for_empty_or_unparsable_created_at(
    created_at: str,
) -> None:
    now = datetime(2026, 8, 17, tzinfo=UTC)
    issue = _make_task(plus_ones=0, created_at=created_at)

    assert stale_task_bead(issue, min_plus_ones=1, stale_after_days=7, now=now) is False


def test_stale_task_bead_false_for_naive_created_at() -> None:
    now = datetime(2026, 8, 17, tzinfo=UTC)
    issue = _make_task(plus_ones=0, created_at="2026-08-01T09:14:02")

    assert stale_task_bead(issue, min_plus_ones=1, stale_after_days=7, now=now) is False


def test_effective_min_plus_ones_uses_the_type_spec_bar() -> None:
    issue = _make_task(task_type="flake")
    registry = _registry(_task_type_record("flake", min_plus_ones=1))

    assert effective_min_plus_ones(issue, registry=registry, global_default=9) == 1


def test_effective_min_plus_ones_defaults_a_typed_bead_with_no_triage_key_to_zero() -> (
    None
):
    issue = _make_task(task_type="bug")
    registry = _registry(_task_type_record("bug", min_plus_ones=None))

    assert effective_min_plus_ones(issue, registry=registry, global_default=9) == 0


def test_effective_min_plus_ones_falls_back_to_global_default_for_untyped_bead() -> (
    None
):
    issue = _make_task(task_type="")
    registry = _registry(_task_type_record("flake", min_plus_ones=1))

    assert effective_min_plus_ones(issue, registry=registry, global_default=9) == 9


def test_effective_min_plus_ones_falls_back_to_global_default_for_unregistered_type() -> (
    None
):
    issue = _make_task(task_type="not_installed_here")
    registry = _registry(_task_type_record("flake", min_plus_ones=1))

    assert effective_min_plus_ones(issue, registry=registry, global_default=9) == 9
