"""In-flight task-launch deferral tests for the task triage chop."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

import sase.scripts.sase_chop_bead_task_triage as task_triage
from sase.bead import work_liveness
from sase.bead.model import TaskPlusOneEvidence

from tests._axe_chop_bead_task_triage_helpers import (
    _default_task_triage_min_plus_ones,  # noqa: F401 (registers the min_plus_ones fixture)
    make_runtime,
    make_task,
    patch_active_launches,
    patch_project,
)


def test_terminal_gate_for_task_with_launch_in_flight_is_deferred_then_regenerated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ready = [make_task()]
    patch_project(monkeypatch, tmp_path, ready)
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )

    task_triage._run(make_runtime(tmp_path))
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "terminal")
    patch_active_launches(monkeypatch, {"sase-task.1"})

    deferred = task_triage._run(make_runtime(tmp_path))

    assert deferred.reason == "no_triage_changes"
    assert deferred.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 0,
        "deferred": 1,
        "resnoozed": 0,
        "suppressed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert len(created) == 1
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)["sase"]
    assert state.gates == {}
    assert state.generations == {"sase-task.1": 1}

    patch_active_launches(monkeypatch)
    regenerated = task_triage._run(make_runtime(tmp_path))

    assert regenerated.counters == {
        "gated": 1,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert len(created) == 2
    assert created[1].endswith("-g2")


def test_ready_task_with_launch_in_flight_is_not_gated_or_recorded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_project(monkeypatch, tmp_path, [make_task()])
    patch_active_launches(monkeypatch, {"sase-task.1"})
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.reason == "no_triage_changes"
    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 0,
        "deferred": 1,
        "resnoozed": 0,
        "suppressed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert created == []
    assert not (tmp_path / task_triage._STATE_FILENAME).exists()


def test_pending_gate_with_launch_in_flight_ignores_presentation_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = make_task()
    patch_project(monkeypatch, tmp_path, [task])
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")

    task_triage._run(make_runtime(tmp_path))
    task.notes = "Fresh evidence landed while the launch is still starting."
    patch_active_launches(monkeypatch, {"sase-task.1"})
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda *_args, **_kwargs: pytest.fail("in-flight gate was canceled"),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.reason == "no_triage_changes"
    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 1,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert len(created) == 1
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)["sase"]
    assert state.gates == {"sase-task.1": created[0]}


def test_suppressed_bead_with_launch_in_flight_is_deferred_not_canceled(
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
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")

    task_triage._run(make_runtime(tmp_path))

    task.plus_one_evidence = []
    patch_active_launches(monkeypatch, {"sase-task.1"})
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda *_args, **_kwargs: pytest.fail(
            "suppressed gate with an in-flight launch was canceled"
        ),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 1,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 1,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)
    assert state["sase"].gates == {"sase-task.1": created[0]}


def test_active_task_launch_read_failure_falls_back_to_existing_behavior(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_project(monkeypatch, tmp_path, [make_task()])
    monkeypatch.setattr(
        task_triage,
        "bead_work_in_flight",
        work_liveness.bead_work_in_flight,
    )
    monkeypatch.setattr(
        work_liveness,
        "active_task_launch_bead_ids",
        lambda: (_ for _ in ()).throw(OSError("task store busy")),
    )
    monkeypatch.setattr(task_triage, "beads_with_live_agents", lambda **_kwargs: {})
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )
    runtime = make_runtime(tmp_path)

    result = task_triage._run(runtime)

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
    assert isinstance(runtime.log._stderr, StringIO)
    assert "Failed to read active task launches: task store busy" in (
        runtime.log._stderr.getvalue()
    )
