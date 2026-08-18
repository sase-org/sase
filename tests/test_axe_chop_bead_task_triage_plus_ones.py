"""``+1`` threshold suppression tests for the task triage chop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_bead_task_triage as task_triage
from sase.bead.model import TaskPlusOneEvidence
from sase.task_types._models import (
    TaskTypeProvenance,
    TaskTypeRecord,
    TaskTypeRegistry,
)

from tests._axe_chop_bead_task_triage_helpers import (
    _default_task_triage_min_plus_ones,  # noqa: F401 (registers the min_plus_ones fixture)
    make_due_flag,
    make_runtime,
    make_snoozed_task,
    make_task,
    patch_project,
    patch_snooze_gate,
    patch_task_type_registry,
)


def _flake_task_type_registry(*, min_plus_ones: int) -> TaskTypeRegistry:
    record = TaskTypeRecord(
        task_type="flake",
        spec={"task_type": "flake", "triage": {"min_plus_ones": min_plus_ones}},
        digest="a" * 64,
        provenance=TaskTypeProvenance(
            source="builtin", name="sase", package="sase", version="1.0.0", builtin=True
        ),
    )
    return TaskTypeRegistry(records=(record,), diagnostics=())


def test_ready_task_below_plus_one_bar_gets_no_gate_and_is_counted_suppressed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_project(monkeypatch, tmp_path, [make_task()], min_plus_ones=1)
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 1,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert created == []
    assert not (tmp_path / task_triage._STATE_FILENAME).exists()


def test_ready_task_at_plus_one_bar_still_gets_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = make_task()
    task.plus_one_evidence = [
        TaskPlusOneEvidence(
            timestamp="2026-01-02T00:00:00Z", reporter="bryan", note="me too"
        )
    ]
    patch_project(monkeypatch, tmp_path, [task], min_plus_ones=1)
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 1,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert len(created) == 1


def test_tracked_gate_falling_below_bar_is_canceled_with_threshold_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = make_task()
    task.plus_one_evidence = [
        TaskPlusOneEvidence(
            timestamp="2026-01-02T00:00:00Z", reporter="bryan", note="me too"
        )
    ]
    patch_project(monkeypatch, tmp_path, [task], min_plus_ones=1)
    created: list[str] = []
    canceled: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda kind, request_id, *, reason: (
            canceled.append((kind, request_id, reason)) or True
        ),
    )

    task_triage._run(make_runtime(tmp_path))
    task.plus_one_evidence = []

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 0,
        "canceled": 1,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 1,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert canceled == [
        (
            task_triage.TASK_TRIAGE_KIND,
            created[0],
            "task_bead_below_plus_one_threshold",
        )
    ]
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)
    assert state["sase"].gates == {}


def test_snoozed_and_due_flag_beads_are_gated_regardless_of_plus_one_bar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snoozed = make_snoozed_task()
    due_flag = make_due_flag()
    patch_project(monkeypatch, tmp_path, [snoozed, due_flag], min_plus_ones=5)
    snooze_created: list[dict[str, Any]] = []
    flag_created: list[dict[str, Any]] = []
    patch_snooze_gate(monkeypatch, snooze_created)
    monkeypatch.setattr(
        task_triage,
        "create_flag_triage_gate",
        lambda **kwargs: flag_created.append(kwargs),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 2,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert len(snooze_created) == 1
    assert len(flag_created) == 1


def test_min_plus_ones_zero_reproduces_pre_epic_gating(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_project(monkeypatch, tmp_path, [make_task()], min_plus_ones=0)
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 1,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert len(created) == 1


def test_typed_task_below_its_own_type_bar_is_suppressed_despite_low_global_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_project(
        monkeypatch, tmp_path, [make_task(task_type="flake")], min_plus_ones=0
    )
    patch_task_type_registry(monkeypatch, _flake_task_type_registry(min_plus_ones=1))
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 1,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert created == []


def test_typed_task_above_high_global_default_still_gates_at_its_own_lower_bar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_project(
        monkeypatch, tmp_path, [make_task(task_type="flake")], min_plus_ones=5
    )
    patch_task_type_registry(monkeypatch, _flake_task_type_registry(min_plus_ones=0))
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 1,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert len(created) == 1
