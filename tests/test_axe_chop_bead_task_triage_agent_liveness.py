"""Live-agent work-in-flight tests for the task triage chop."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_bead_task_triage as task_triage
from sase.bead import work_liveness

from tests._axe_chop_bead_task_triage_helpers import (
    _default_task_triage_min_plus_ones,  # noqa: F401 (registers the min_plus_ones fixture)
    make_due_flag,
    make_runtime,
    make_task,
    patch_active_launches,
    patch_live_agent_beads,
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


def test_ready_task_with_live_agent_is_not_gated_or_recorded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_project(monkeypatch, tmp_path, [make_task()])
    patch_live_agent_beads(monkeypatch, {("sase", "sase-task.1")})
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )
    runtime = make_runtime(tmp_path)

    result = task_triage._run(runtime)

    assert result.reason == "no_triage_changes"
    assert result.counters == _empty_counters(deferred=1)
    assert created == []
    assert not (tmp_path / task_triage._STATE_FILENAME).exists()
    assert isinstance(runtime.log._stdout, StringIO)
    assert "Live agent sase-task.1 is working sase:sase-task.1" in (
        runtime.log._stdout.getvalue()
    )


def test_pending_gate_with_live_agent_is_canceled_and_not_regated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_project(monkeypatch, tmp_path, [make_task()])
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
    patch_live_agent_beads(monkeypatch, {("sase", "sase-task.1")})
    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == _empty_counters(canceled=1, deferred=1)
    assert canceled == [
        (task_triage.TASK_TRIAGE_KIND, created[0], "bead_work_in_flight")
    ]
    assert len(created) == 1
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)["sase"]
    assert state.gates == {}
    assert state.generations == {"sase-task.1": 1}


def test_pending_gate_with_live_agent_outranks_presentation_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = make_task()
    patch_project(monkeypatch, tmp_path, [task])
    created: list[str] = []
    canceled: list[tuple[str, str]] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda _kind, request_id, *, reason: (
            canceled.append((request_id, reason)) or True
        ),
    )

    task_triage._run(make_runtime(tmp_path))
    task.notes = "Fresh evidence landed while the agent is already working."
    patch_live_agent_beads(monkeypatch, {("sase", "sase-task.1")})
    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == _empty_counters(canceled=1, deferred=1)
    assert canceled == [(created[0], "bead_work_in_flight")]
    assert len(created) == 1


def test_pending_gate_with_launch_and_no_live_agent_is_left_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_project(monkeypatch, tmp_path, [make_task()])
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")

    task_triage._run(make_runtime(tmp_path))
    patch_active_launches(monkeypatch, {"sase-task.1"})
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda *_args, **_kwargs: pytest.fail("in-flight gate was canceled"),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == _empty_counters(skipped=1)
    assert len(created) == 1
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)["sase"]
    assert state.gates == {"sase-task.1": created[0]}


def test_live_agent_on_other_project_does_not_suppress_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_project(monkeypatch, tmp_path, [make_task()])
    patch_live_agent_beads(monkeypatch, {("other", "sase-task.1")})
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == _empty_counters(gated=1)
    assert len(created) == 1


def test_live_agent_going_away_regates_with_next_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_project(monkeypatch, tmp_path, [make_task()])
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda *_args, **_kwargs: True,
    )

    task_triage._run(make_runtime(tmp_path))
    patch_live_agent_beads(monkeypatch, {("sase", "sase-task.1")})
    task_triage._run(make_runtime(tmp_path))
    patch_live_agent_beads(monkeypatch)
    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == _empty_counters(gated=1)
    assert len(created) == 2
    assert created[1].endswith("-g2")


def test_due_flag_with_live_agent_is_deferred(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_project(monkeypatch, tmp_path, [make_due_flag()])
    patch_live_agent_beads(monkeypatch, {("sase", "sase-flag.1")})
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


def test_live_agent_scan_failure_falls_back_to_gating(
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
        lambda: frozenset(),
    )
    monkeypatch.setattr(
        task_triage,
        "beads_with_live_agents",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("scan busy")),
    )
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )
    runtime = make_runtime(tmp_path)

    result = task_triage._run(runtime)

    assert result.counters == _empty_counters(gated=1)
    assert len(created) == 1
    assert isinstance(runtime.log._stderr, StringIO)
    assert (
        "Failed to scan live agent beads: scan busy" in runtime.log._stderr.getvalue()
    )
