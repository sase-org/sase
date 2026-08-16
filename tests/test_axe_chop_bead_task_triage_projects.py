"""Project inventory reconciliation tests for the bead_task_triage chop."""

from __future__ import annotations

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

    def read(path: Path, **_kwargs: Any) -> list[Issue]:
        if path.name == "broken":
            raise OSError("unavailable")
        return [make_task()]

    monkeypatch.setattr(task_triage, "_gateable_beads", read)
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
    monkeypatch.setattr(task_triage, "_gateable_beads", lambda _path, **_kwargs: [])
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


def test_reenabled_project_starts_fresh_gate_generation_after_sweep(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old_request_id = task_triage._request_id(
        "sase",
        "sase-task.1",
        4,
        task_triage.TASK_TRIAGE_KIND,
    )
    task_triage._write_state(
        tmp_path / task_triage._STATE_FILENAME,
        {
            "sase": task_triage._ProjectState(
                gates={"sase-task.1": old_request_id},
                generations={"sase-task.1": 4},
            )
        },
    )
    stores: list[tuple[str, Path]] = []
    ready = [make_task()]
    monkeypatch.setattr(
        task_triage,
        "_enabled_project_stores",
        lambda _log: task_triage._ProjectInventory(stores=tuple(stores)),
    )
    monkeypatch.setattr(
        task_triage, "_gateable_beads", lambda _path, **_kwargs: list(ready)
    )
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
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )

    swept = task_triage._run(make_runtime(tmp_path))
    swept_state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)
    stores.append(("sase", tmp_path / "beads"))
    regated = task_triage._run(make_runtime(tmp_path))

    assert swept.counters == {
        "gated": 0,
        "canceled": 1,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 1,
        "untracked_canceled": 0,
    }
    assert canceled == [
        (
            task_triage.TASK_TRIAGE_KIND,
            old_request_id,
            "project_no_longer_enabled",
        )
    ]
    assert swept_state == {}
    assert regated.counters == {
        "gated": 1,
        "canceled": 0,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert created == [
        task_triage._request_id(
            "sase",
            "sase-task.1",
            1,
            task_triage.TASK_TRIAGE_KIND,
        )
    ]
    assert created[0].endswith("-g1")
    assert created[0] != old_request_id


def test_removed_project_key_does_not_duplicate_same_live_bead_in_new_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = make_task()
    stale_request_id = task_triage._request_id(
        "old-sase",
        task.id,
        3,
        task_triage.TASK_TRIAGE_KIND,
    )
    expected_request_id = task_triage._request_id(
        "sase",
        task.id,
        1,
        task_triage.TASK_TRIAGE_KIND,
    )
    task_triage._write_state(
        tmp_path / task_triage._STATE_FILENAME,
        {
            "old-sase": task_triage._ProjectState(
                gates={task.id: stale_request_id},
                generations={task.id: 3},
            )
        },
    )
    pending_request_ids = {stale_request_id}
    monkeypatch.setattr(
        task_triage,
        "_enabled_project_stores",
        lambda _log: task_triage._ProjectInventory(
            stores=(("sase", tmp_path / "beads"),)
        ),
    )
    monkeypatch.setattr(task_triage, "_gateable_beads", lambda _path, **_kwargs: [task])
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    patch_active_launches(monkeypatch)
    canceled: list[tuple[str, str, str]] = []

    def cancel_gate(kind: str, request_id: str, *, reason: str) -> bool:
        canceled.append((kind, request_id, reason))
        pending_request_ids.discard(request_id)
        return True

    def pending_gates(_kinds: tuple[str, ...]) -> list[_PendingBeadGate]:
        return [
            _PendingBeadGate(
                kind=task_triage.TASK_TRIAGE_KIND,
                request_id=request_id,
                project="old-sase" if request_id == stale_request_id else "sase",
                bead_id=task.id,
                producer_chop="bead_task_triage",
            )
            for request_id in sorted(pending_request_ids)
        ]

    monkeypatch.setattr(task_triage, "_cancel_pending_gate", cancel_gate)
    monkeypatch.setattr(task_triage, "find_pending_bead_gates", pending_gates)
    created: list[str] = []

    def create_gate(**kwargs: Any) -> None:
        created.append(kwargs["request_id"])
        pending_request_ids.add(kwargs["request_id"])

    monkeypatch.setattr(task_triage, "create_task_triage_gate", create_gate)

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 1,
        "canceled": 1,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "swept_projects": 1,
        "untracked_canceled": 0,
    }
    assert created == [expected_request_id]
    assert canceled == [
        (
            task_triage.TASK_TRIAGE_KIND,
            stale_request_id,
            "project_no_longer_enabled",
        )
    ]
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)
    assert set(state) == {"sase"}
    assert state["sase"].gates == {task.id: expected_request_id}
    assert pending_request_ids == {expected_request_id}


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
        "_gateable_beads",
        lambda _path, **_kwargs: (_ for _ in ()).throw(OSError("store unavailable")),
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
