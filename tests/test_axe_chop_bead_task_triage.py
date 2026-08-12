"""Live task-bead gate reconciliation chop tests."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_bead_task_triage as task_triage
from sase.bead.gate_lookup import _PendingBeadGate
from sase.bead.model import Issue

from tests._axe_chop_bead_task_triage_helpers import (
    make_runtime,
    make_task,
    patch_active_launches,
    patch_project,
)


def test_ready_task_is_gated_once_while_gate_remains_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ready = [make_task()]
    patch_project(monkeypatch, tmp_path, ready)
    created: list[dict[str, Any]] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")

    first = task_triage._run(make_runtime(tmp_path))
    second = task_triage._run(make_runtime(tmp_path))

    assert first.counters == {
        "gated": 1,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert second.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 1,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert second.reason == "no_triage_changes"
    assert len(created) == 1
    assert created[0]["bead_id"] == "sase-task.1"
    assert created[0]["project"] == "sase"
    assert created[0]["title"] == "Follow up on cache invalidation"
    assert created[0]["created_by"] == "claude_coder"
    assert created[0]["created_at"] == "2026-01-01T00:00:00Z"
    assert created[0]["request_id"].endswith("-g1")

    state = json.loads(
        (tmp_path / task_triage._STATE_FILENAME).read_text(encoding="utf-8")
    )
    assert state["projects"]["sase"]["gates"] == {
        "sase-task.1": created[0]["request_id"]
    }
    assert state["projects"]["sase"]["generations"] == {"sase-task.1": 1}
    assert state["projects"]["sase"]["fingerprints"] == {
        "sase-task.1": task_triage._presentation_fingerprint(ready[0])
    }


def test_blank_task_creator_is_forwarded_without_placeholder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_project(monkeypatch, tmp_path, [make_task(created_by="")])
    created: list[dict[str, Any]] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 1,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert created[0]["created_by"] == ""


def test_stale_gate_is_canceled_and_ready_again_uses_new_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ready = [make_task()]
    patch_project(monkeypatch, tmp_path, ready)
    created: list[str] = []
    canceled: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda _kind, request_id: canceled.append(request_id) or True,
    )

    task_triage._run(make_runtime(tmp_path))
    ready.clear()
    stale = task_triage._run(make_runtime(tmp_path))
    ready.append(make_task())
    raised_again = task_triage._run(make_runtime(tmp_path))

    assert stale.counters == {
        "gated": 0,
        "canceled": 1,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert canceled == [created[0]]
    assert raised_again.counters == {
        "gated": 1,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert len(created) == 2
    assert created[0].endswith("-g1")
    assert created[1].endswith("-g2")
    assert created[0] != created[1]


def test_terminal_gate_for_still_ready_task_is_regenerated(
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
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "terminal")

    task_triage._run(make_runtime(tmp_path))
    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 1,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert created[0].endswith("-g1")
    assert created[1].endswith("-g2")


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
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert len(created) == 1
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)["sase"]
    assert state.gates == {"sase-task.1": created[0]}


def test_active_task_launch_read_failure_falls_back_to_existing_behavior(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_project(monkeypatch, tmp_path, [make_task()])
    monkeypatch.setattr(
        task_triage,
        "active_task_launch_bead_ids",
        lambda: (_ for _ in ()).throw(OSError("task store busy")),
    )
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
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert len(created) == 1
    assert isinstance(runtime.log._stderr, StringIO)
    assert "Failed to read active task launches: task store busy" in (
        runtime.log._stderr.getvalue()
    )


def test_failed_project_read_does_not_block_other_projects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_active_launches(monkeypatch)
    monkeypatch.setattr(
        task_triage,
        "_enabled_project_stores",
        lambda _log: [
            ("broken", tmp_path / "broken"),
            ("sase", tmp_path / "beads"),
        ],
    )

    def read(path: Path) -> list[Issue]:
        if path.name == "broken":
            raise OSError("unavailable")
        return [make_task()]

    monkeypatch.setattr(task_triage, "_gateable_tasks", read)
    monkeypatch.setattr(task_triage, "find_pending_bead_gates", lambda _kinds: [])
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
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert len(created) == 1


def test_state_project_absent_from_inventory_is_swept(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task_triage._write_state(
        tmp_path / task_triage._STATE_FILENAME,
        {
            "removed": task_triage._ProjectState(
                gates={"sase-old.1": "old-request"},
                generations={"sase-old.1": 4},
            )
        },
    )
    monkeypatch.setattr(
        task_triage,
        "_enabled_project_stores",
        lambda _log: task_triage._ProjectInventory(
            stores=(("sase", tmp_path / "beads"),)
        ),
    )
    monkeypatch.setattr(task_triage, "_gateable_tasks", lambda _path: [])
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(task_triage, "find_pending_bead_gates", lambda _kinds: [])
    patch_active_launches(monkeypatch)
    canceled: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda kind, request_id, *, reason: (
            canceled.append((kind, request_id, reason)) or True
        ),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 0,
        "canceled": 1,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 1,
        "untracked_canceled": 0,
    }
    assert result.reason is None
    assert canceled == [
        (
            task_triage.TASK_TRIAGE_KIND,
            "old-request",
            "project_no_longer_enabled",
        )
    ]
    assert task_triage._read_state(tmp_path / task_triage._STATE_FILENAME) == {}


def test_unreadable_inventory_project_keeps_state_and_pending_gates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task_triage._write_state(
        tmp_path / task_triage._STATE_FILENAME,
        {
            "sase": task_triage._ProjectState(
                gates={"sase-task.1": "tracked-request"},
                generations={"sase-task.1": 2},
            )
        },
    )
    monkeypatch.setattr(
        task_triage,
        "_enabled_project_stores",
        lambda _log: task_triage._ProjectInventory(
            stores=(("sase", tmp_path / "broken"),)
        ),
    )
    monkeypatch.setattr(
        task_triage,
        "_gateable_tasks",
        lambda _path: (_ for _ in ()).throw(OSError("store unavailable")),
    )
    monkeypatch.setattr(
        task_triage,
        "find_pending_bead_gates",
        lambda _kinds: [
            _PendingBeadGate(
                kind=task_triage.TASK_TRIAGE_KIND,
                request_id="forgotten-request",
                project="sase",
                bead_id="sase-task.2",
                producer_chop="bead_task_triage",
            )
        ],
    )
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda *_args, **_kwargs: pytest.fail("unreadable project gate was canceled"),
    )
    patch_active_launches(monkeypatch)

    result = task_triage._run(make_runtime(tmp_path))

    assert result.reason == "no_triage_changes"
    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)
    assert state["sase"].gates == {"sase-task.1": "tracked-request"}
    assert state["sase"].generations == {"sase-task.1": 2}


def test_empty_inventory_read_sweeps_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task_triage._write_state(
        tmp_path / task_triage._STATE_FILENAME,
        {
            "removed": task_triage._ProjectState(
                gates={"sase-old.1": "old-request"},
                generations={"sase-old.1": 1},
            )
        },
    )
    monkeypatch.setattr(
        task_triage,
        "_enabled_project_stores",
        lambda _log: task_triage._ProjectInventory(
            stores=(),
            sweep_allowed=False,
        ),
    )
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda *_args, **_kwargs: pytest.fail("empty inventory swept a gate"),
    )
    monkeypatch.setattr(
        task_triage,
        "find_pending_bead_gates",
        lambda _kinds: pytest.fail("empty inventory scanned pending gates"),
    )
    patch_active_launches(monkeypatch)

    result = task_triage._run(make_runtime(tmp_path))

    assert result.reason == "no_triage_changes"
    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert "removed" in task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)


def test_inventory_failure_sweeps_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task_triage._write_state(
        tmp_path / task_triage._STATE_FILENAME,
        {
            "removed": task_triage._ProjectState(
                gates={"sase-old.1": "old-request"},
                generations={"sase-old.1": 1},
            )
        },
    )
    monkeypatch.setattr(
        task_triage,
        "_enabled_project_stores",
        lambda _log: (_ for _ in ()).throw(OSError("inventory unavailable")),
    )
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda *_args, **_kwargs: pytest.fail("failed inventory swept a gate"),
    )
    patch_active_launches(monkeypatch)

    result = task_triage._run(make_runtime(tmp_path))

    assert result.reason == "project_inventory_unavailable"
    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert "removed" in task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)


def test_pending_gate_produced_by_chop_but_missing_from_state_is_canceled(
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
    expected_request_id = task_triage._request_id(
        "sase",
        task.id,
        1,
        task_triage.TASK_TRIAGE_KIND,
    )
    monkeypatch.setattr(
        task_triage,
        "find_pending_bead_gates",
        lambda _kinds: [
            _PendingBeadGate(
                kind=task_triage.TASK_TRIAGE_KIND,
                request_id=expected_request_id,
                project="sase",
                bead_id=task.id,
                producer_chop="bead_task_triage",
            ),
            _PendingBeadGate(
                kind=task_triage.TASK_TRIAGE_KIND,
                request_id="forgotten-request",
                project="sase",
                bead_id="sase-task.2",
                producer_chop="bead_task_triage",
            ),
            _PendingBeadGate(
                kind=task_triage.TASK_TRIAGE_KIND,
                request_id="other-producer-request",
                project="sase",
                bead_id="sase-task.3",
                producer_chop="other_chop",
            ),
        ],
    )
    patch_active_launches(monkeypatch)
    canceled: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda kind, request_id, *, reason: (
            canceled.append((kind, request_id, reason)) or True
        ),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert created == [expected_request_id]
    assert result.counters == {
        "gated": 1,
        "canceled": 1,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 0,
        "untracked_canceled": 1,
    }
    assert canceled == [
        (
            task_triage.TASK_TRIAGE_KIND,
            "forgotten-request",
            "gate_no_longer_tracked",
        )
    ]


def test_gate_inspection_failure_preserves_mapping_without_duplicate(
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
    monkeypatch.setattr(
        task_triage,
        "_gate_state",
        lambda _kind, _id: (_ for _ in ()).throw(OSError("unreadable gate")),
    )
    result = task_triage._run(make_runtime(tmp_path))

    assert result.reason == "no_triage_changes"
    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert len(created) == 1
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)
    assert state["sase"].gates["sase-task.1"] == created[0]


def test_dry_run_does_not_read_stores_or_mutate_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        task_triage,
        "_enabled_project_stores",
        lambda _log: pytest.fail("dry run enumerated projects"),
    )

    result = task_triage._run(make_runtime(tmp_path, dry_run=True))

    assert result.reason == "dry_run"
    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert not (tmp_path / task_triage._STATE_FILENAME).exists()


def test_request_ids_are_deterministic_project_scoped_kind_scoped_and_bounded() -> None:
    bead_id = "sase-" + ("x" * 120)
    triage = task_triage.TASK_TRIAGE_KIND
    snooze = task_triage.BEAD_SNOOZE_KIND

    first = task_triage._request_id("gh_sase-org__sase", bead_id, 1, triage)
    repeated = task_triage._request_id("gh_sase-org__sase", bead_id, 1, triage)
    other_project = task_triage._request_id("other", bead_id, 1, triage)
    other_kind = task_triage._request_id("gh_sase-org__sase", bead_id, 1, snooze)

    assert first == repeated
    assert first != other_project
    assert first != other_kind
    assert first.endswith("-g1")
    assert len(first) <= 128
    assert len(other_kind) <= 128
