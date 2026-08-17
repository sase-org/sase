"""Flag-bead removal-triage gate reconciliation tests for the task triage chop."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_bead_task_triage as task_triage
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.scripts._bead_task_triage_state import gateable_beads

from tests._axe_chop_bead_task_triage_helpers import (
    make_due_flag,
    make_live_flag,
    make_runtime,
    make_task,
    patch_active_launches,
    patch_project,
)


def _empty_counters(**overrides: int) -> dict[str, int]:
    counters = {
        "gated": 0,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    counters.update(overrides)
    return counters


def test_due_flag_bead_raises_exactly_one_pending_flag_triage_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    due = [make_due_flag()]
    patch_project(monkeypatch, tmp_path, due)
    created: list[dict[str, Any]] = []
    monkeypatch.setattr(
        task_triage,
        "create_flag_triage_gate",
        lambda **kwargs: created.append(kwargs),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")

    first = task_triage._run(make_runtime(tmp_path))
    second = task_triage._run(make_runtime(tmp_path))

    assert first.counters == _empty_counters(gated=1)
    assert second.counters == _empty_counters(skipped=1)
    assert second.reason == "no_triage_changes"
    assert len(created) == 1
    assert created[0]["bead_id"] == "sase-flag.1"
    assert created[0]["project"] == "sase"
    assert created[0]["flag"] is due[0].flag
    assert created[0]["due_state"] == "due"
    assert created[0]["request_id"].startswith("bead-flag-triage-")
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)["sase"]
    assert state.kinds == {"sase-flag.1": task_triage.FLAG_TRIAGE_KIND}


def test_live_or_soon_flag_bead_is_not_gateable(tmp_path: Path) -> None:
    with BeadProject.init(tmp_path) as proj:
        live = proj.create(
            "Remove the live flag",
            IssueType.FLAG,
            flag=make_live_flag().flag,
        )
        soon = proj.create(
            "Remove the soon flag",
            IssueType.FLAG,
            flag=make_due_flag(
                remove_by_date="2020-01-01",
                remove_by_release="99.0.0",
            ).flag,
        )

    gateable_ids = {
        issue.id
        for issue in gateable_beads(
            proj.beads_dir, today=date(2026, 8, 16), release="0.16.0"
        )
    }
    assert live.id not in gateable_ids
    assert soon.id not in gateable_ids


def test_due_flag_bead_is_gateable_only_while_open(tmp_path: Path) -> None:
    with BeadProject.init(tmp_path) as proj:
        due = proj.create(
            "Remove the due flag",
            IssueType.FLAG,
            flag=make_due_flag().flag,
        )
        proj.update(due.id, status="in_progress")

    gateable_ids = {
        issue.id
        for issue in gateable_beads(
            proj.beads_dir, today=date(2026, 8, 16), release="0.16.0"
        )
    }
    assert due.id not in gateable_ids


def test_flag_bead_with_in_flight_launch_is_deferred(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_project(monkeypatch, tmp_path, [make_due_flag()])
    patch_active_launches(monkeypatch, {"sase-flag.1"})
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_flag_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.reason == "no_triage_changes"
    assert result.counters == _empty_counters(deferred=1)
    assert created == []


def test_flag_bead_thresholds_moved_replaces_its_pending_gate_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    flags = [make_due_flag()]
    patch_project(monkeypatch, tmp_path, flags)
    created: list[str] = []
    canceled: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        task_triage,
        "create_flag_triage_gate",
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
    flags[:] = [make_due_flag(remove_by_date="2026-02-01")]
    replaced = task_triage._run(make_runtime(tmp_path))

    assert replaced.counters == _empty_counters(gated=1, canceled=1)
    assert canceled == [
        (task_triage.FLAG_TRIAGE_KIND, created[0], "task_triage_presentation_changed")
    ]
    assert len(created) == 2
    assert created[0] != created[1]


def test_task_bead_gate_is_not_duplicated_when_a_flag_bead_is_also_reconciled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = make_task()
    flag = make_due_flag(bead_id="sase-flag.1")
    patch_project(monkeypatch, tmp_path, [task, flag])
    task_created: list[dict[str, Any]] = []
    flag_created: list[dict[str, Any]] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: task_created.append(kwargs),
    )
    monkeypatch.setattr(
        task_triage,
        "create_flag_triage_gate",
        lambda **kwargs: flag_created.append(kwargs),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")

    first = task_triage._run(make_runtime(tmp_path))
    second = task_triage._run(make_runtime(tmp_path))

    assert first.counters == _empty_counters(gated=2)
    assert second.counters == _empty_counters(skipped=2)
    assert len(task_created) == 1
    assert len(flag_created) == 1
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)["sase"]
    assert state.kinds == {
        task.id: task_triage.TASK_TRIAGE_KIND,
        flag.id: task_triage.FLAG_TRIAGE_KIND,
    }
