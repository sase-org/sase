"""Backoff, schedule state, and work-budget tests for the sidecar auto-sync chop."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import sase.scripts.sase_chop_sidecar_auto_sync as sidecar_sync_chop
from sase._sidecar_auto_sync import SidecarSyncResult
from tests._axe_chop_sidecar_auto_sync_support import (
    configure_sidecar_sync,
    make_project,
    make_runtime,
)


def test_successful_sync_defers_maintenance_when_work_budget_is_exhausted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    clone_dir = Path(project.workspace_dir) / "sase" / "repos" / "plans"
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[project],
        roles_by_project={"proj": ("plans",)},
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "sync_primary_sidecar_role",
        MagicMock(
            return_value=SidecarSyncResult(
                "proj",
                "plans",
                "refreshed",
                "fast-forwarded",
                str(clone_dir),
            )
        ),
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "maybe_gc_sidecar_clone",
        lambda *_a: pytest.fail("budget-exhausted maintenance ran"),
    )
    clock = iter([0.0, 0.0, sidecar_sync_chop._WORK_BUDGET_SECONDS + 1.0])
    monkeypatch.setattr(
        sidecar_sync_chop,
        "time",
        SimpleNamespace(monotonic=lambda: next(clock)),
    )

    result = sidecar_sync_chop._run(make_runtime(tmp_path))

    assert result.counters["refreshed"] == 1
    assert result.counters["deferred"] == 1


def test_unhinted_role_backstops_then_skips_within_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={"proj": ("beads",)},
    )
    now = datetime(2026, 7, 26, 12, tzinfo=UTC)
    current_time = [now]
    monkeypatch.setattr(sidecar_sync_chop, "_utc_now", lambda: current_time[0])
    sync = MagicMock(
        return_value=SidecarSyncResult("proj", "beads", "up_to_date", "already fresh")
    )
    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)
    runtime = make_runtime(tmp_path)

    first = sidecar_sync_chop._run(runtime)
    second = sidecar_sync_chop._run(runtime)

    assert sync.call_count == 1
    assert first.counters["up_to_date"] == 1
    assert second.counters["backed_off"] == 1

    current_time[0] = now + timedelta(
        seconds=sidecar_sync_chop._BACKSTOP_INTERVAL_SECONDS + 1
    )
    third = sidecar_sync_chop._run(runtime)

    assert sync.call_count == 2
    assert third.counters["up_to_date"] == 1


def test_failure_like_status_backs_off_exponentially(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={"proj": ("research",)},
    )
    now = datetime(2026, 7, 26, 12, tzinfo=UTC)
    current_time = [now]
    monkeypatch.setattr(sidecar_sync_chop, "_utc_now", lambda: current_time[0])
    sync = MagicMock(
        return_value=SidecarSyncResult("proj", "research", "dirty", "local changes")
    )
    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)
    runtime = make_runtime(tmp_path)

    failed = sidecar_sync_chop._run(runtime)
    backed_off = sidecar_sync_chop._run(runtime)

    assert failed.counters["failed"] == 1
    assert failed.reason == "sync_failed"
    assert backed_off.counters["backed_off"] == 1
    assert sync.call_count == 1

    state_path = (
        Path(runtime.context.state_dir) / sidecar_sync_chop._BACKOFF_STATE_FILENAME
    )
    stored = json.loads(state_path.read_text(encoding="utf-8"))
    assert stored["proj:research"]["failures"] == 1


def test_hinted_role_bypasses_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={"proj": ("beads",)},
        hinted_by_project={"proj": ()},
    )
    now = datetime(2026, 7, 26, 12, tzinfo=UTC)
    current_time = [now]
    monkeypatch.setattr(sidecar_sync_chop, "_utc_now", lambda: current_time[0])
    outcomes = iter(
        [
            SidecarSyncResult("proj", "beads", "dirty", "local changes"),
            SidecarSyncResult("proj", "beads", "refreshed", "fast-forwarded"),
        ]
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "sync_primary_sidecar_role",
        lambda *_a, **_kw: next(outcomes),
    )
    monkeypatch.setattr(sidecar_sync_chop, "clear_sidecar_sync_hint", MagicMock())
    runtime = make_runtime(tmp_path)

    sidecar_sync_chop._run(runtime)

    # A hint arrives before the exponential backoff window would allow a
    # normal retry; the hinted attempt still runs immediately.
    monkeypatch.setattr(
        sidecar_sync_chop, "pending_sidecar_sync_roles", lambda _project_key: ("beads",)
    )
    hinted = sidecar_sync_chop._run(runtime)

    assert hinted.counters["refreshed"] == 1
    assert hinted.counters["backed_off"] == 0


def test_stale_schedule_entries_are_pruned_for_deconfigured_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path, name="alive")],
        roles_by_project={"alive": ("plans",)},
    )
    runtime = make_runtime(tmp_path)
    state_path = (
        Path(runtime.context.state_dir) / sidecar_sync_chop._BACKOFF_STATE_FILENAME
    )
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "gone:beads": {
                    "failures": 3,
                    "next_attempt_at": "2099-01-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "sync_primary_sidecar_role",
        lambda project, role, **_kw: SidecarSyncResult(
            project, role, "up_to_date", "already fresh"
        ),
    )

    result = sidecar_sync_chop._run(runtime)

    assert result.counters["up_to_date"] == 1
    assert "gone:beads" not in json.loads(state_path.read_text(encoding="utf-8"))


def test_exhausted_work_budget_defers_remaining_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[
            make_project(tmp_path, name="one"),
            make_project(tmp_path, name="two"),
        ],
        roles_by_project={"one": ("plans",), "two": ("plans",)},
    )
    clock = iter([0.0, 0.0, sidecar_sync_chop._WORK_BUDGET_SECONDS + 1.0])
    monkeypatch.setattr(
        sidecar_sync_chop,
        "time",
        SimpleNamespace(monotonic=lambda: next(clock)),
    )
    sync = MagicMock(
        return_value=SidecarSyncResult("one", "plans", "up_to_date", "already fresh")
    )
    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)

    result = sidecar_sync_chop._run(make_runtime(tmp_path))

    assert sync.call_count == 1
    assert result.counters["up_to_date"] == 1
    assert result.counters["deferred"] == 1


def test_corrupt_schedule_state_is_treated_as_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={"proj": ("plans",)},
    )
    runtime = make_runtime(tmp_path)
    state_path = (
        Path(runtime.context.state_dir) / sidecar_sync_chop._BACKOFF_STATE_FILENAME
    )
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{not-json", encoding="utf-8")
    sync = MagicMock(
        return_value=SidecarSyncResult("proj", "plans", "refreshed", "fast-forwarded")
    )
    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)

    result = sidecar_sync_chop._run(runtime)

    sync.assert_called_once()
    assert result.counters["refreshed"] == 1
