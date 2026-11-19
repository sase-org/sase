"""Tests for disk-pressure recovery helpers."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

from sase.core.disk_footprint_models import DISK_SIZE_UNMEASURED
from sase.core.disk_footprint_models import DiskFootprintRow
from sase.core.disk_pressure_recovery import (
    build_escalation_notes,
    build_pressure_notes,
    collect_inventory_fail_open,
    end_all_episodes,
    end_inactive_episodes,
    filesystem_id,
    pressure_escalation_key,
    pressure_notice_key,
    start_or_continue_episode,
)
from sase.core.disk_pressure_recovery import _episode_state_path


def _report(*rows: DiskFootprintRow, unmeasured_owners: tuple[str, ...] = ()):
    return SimpleNamespace(rows=rows, unmeasured_owners=unmeasured_owners)


def _row(
    owner: str,
    size: int,
    *,
    path: str = "/somewhere",
    size_state: str = "measured",
    reclaim: str | None = "sase disk reap --apply",
    horizon: str = "test",
    name: str | None = None,
) -> DiskFootprintRow:
    return DiskFootprintRow(
        section="filesystem" if owner == "unattributed" else "managed_tmp",
        name=name or owner,
        path="" if owner == "unattributed" else path,
        size_bytes=size,
        owner=owner,
        horizon=horizon,
        exclusive_size_bytes=size,
        size_state=size_state,
        reclaim=reclaim,
    )


def _pressure_row() -> dict[str, object]:
    return {
        "label": "managed_tmp",
        "path": "/tmp/managed",
        "free_bytes": 2 * 1024**3,
    }


def test_collect_inventory_fail_open_returns_report() -> None:
    report = _report()
    attempt = collect_inventory_fail_open(lambda: report, timeout_seconds=1)
    assert attempt.report is report
    assert attempt.unavailable_reason is None


def test_collect_inventory_fail_open_captures_exception() -> None:
    attempt = collect_inventory_fail_open(
        lambda: (_ for _ in ()).throw(RuntimeError("scan broke")),
        timeout_seconds=1,
    )
    assert attempt.report is None
    assert attempt.unavailable_reason is not None
    assert attempt.unavailable_reason.startswith("RuntimeError: scan broke")


def test_collect_inventory_fail_open_times_out() -> None:
    started = threading.Event()
    release = threading.Event()

    def hang() -> object:
        started.set()
        release.wait(timeout=5)
        return _report()

    try:
        attempt = collect_inventory_fail_open(hang, timeout_seconds=0.05)
        assert started.wait(timeout=1)
        assert attempt.report is None
        assert attempt.unavailable_reason == "inventory timed out"
    finally:
        release.set()


def test_episode_state_reuses_id_until_space_ok(tmp_path: Path) -> None:
    first = start_or_continue_episode(tmp_path, "managed_tmp")
    second = start_or_continue_episode(tmp_path, "managed_tmp")
    assert first == second
    payload = json.loads(_episode_state_path(tmp_path).read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["episodes"]["managed_tmp"]["episode_id"] == first
    end_inactive_episodes(tmp_path, {"sase_home"})
    third = start_or_continue_episode(tmp_path, "managed_tmp")
    assert third != first
    end_all_episodes(tmp_path)
    assert (
        json.loads(_episode_state_path(tmp_path).read_text(encoding="utf-8"))[
            "episodes"
        ]
        == {}
    )


def test_corrupt_episode_state_starts_a_new_episode(tmp_path: Path) -> None:
    path = _episode_state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")
    episode_id = start_or_continue_episode(tmp_path, "managed_tmp")
    assert episode_id
    assert start_or_continue_episode(tmp_path, "managed_tmp") == episode_id


def test_notice_leads_with_free_space_and_names_unmeasured_owners() -> None:
    report = _report(
        _row(
            "unattributed",
            90,
            horizon="space outside measured rows; includes 1 unmeasured owner: ws",
            name="outside measured rows",
        ),
        _row("workspace_cleanup_and_compact", 50, reclaim="sase workspace compact"),
        unmeasured_owners=("workspace_cleanup_and_compact /tmp/ws",),
    )
    notes = build_pressure_notes(
        pressure_row=_pressure_row(),
        free_percent=2.0,
        reclaimed_bytes=256,
        available_after_bytes=2 * 1024**3,
        recovery_target_bytes=5 * 1024**3,
        top_rows=(
            {
                "owner": "workspace_cleanup_and_compact",
                "size_bytes": 50,
                "path": "/tmp/ws",
                "size_state": "measured",
            },
            {
                "owner": "unattributed",
                "size_bytes": 90,
                "path": "",
                "size_state": "measured",
            },
        ),
        report=report,
        unavailable_reason=None,
        changed_owners=("managed_tmp_reaper",),
        failed_owners=(),
        blocked_owners=(),
        incomplete_owners=(),
    )
    assert notes[0].startswith("SASE disk pressure:")
    assert notes[1].startswith("Recovery:")
    assert "Unmeasured owner (1): workspace_cleanup_and_compact /tmp/ws" in notes
    assert any(line.startswith("Top measured owners:") for line in notes)
    assert "unattributed" not in notes[3]
    assert any(line.startswith("Residual") for line in notes)
    assert notes[0].find("Unattributed") == -1


def test_notice_omits_unmeasured_top_owners_and_reports_unavailable() -> None:
    notes = build_pressure_notes(
        pressure_row=_pressure_row(),
        free_percent=2.0,
        reclaimed_bytes=0,
        available_after_bytes=None,
        recovery_target_bytes=5 * 1024**3,
        top_rows=(
            {
                "owner": "workspace_cleanup_and_compact",
                "size_bytes": 0,
                "path": "/tmp/ws",
                "size_state": DISK_SIZE_UNMEASURED,
            },
        ),
        report=None,
        unavailable_reason="inventory timed out",
        changed_owners=(),
        failed_owners=(),
        blocked_owners=(),
        incomplete_owners=(),
    )
    assert notes[2] == "Attribution unavailable: inventory timed out"
    assert all("Top measured owners" not in line for line in notes)


def test_escalation_names_target_reclaimed_blockers_and_unreaped_owners() -> None:
    report = _report(
        _row(
            "workspace_cleanup_and_compact",
            54 * 1024**3,
            reclaim="sase workspace cleanup --stale; sase workspace compact",
        ),
        _row(
            "artifact_run_retention",
            8 * 1024**3,
            reclaim="sase artifact prune-runs",
        ),
        _row("rust_prebuild_cache", 12 * 1024**3, reclaim=None),
    )
    notes = build_escalation_notes(
        pressure_row=_pressure_row(),
        reclaimed_bytes=97 * 1024,
        available_after_bytes=2 * 1024**3,
        recovery_target_bytes=9 * 1024**3,
        owners=(
            {
                "owner": "managed_tmp_reaper",
                "status": "incomplete",
                "reasons": ["incomplete"],
            },
            {
                "owner": "managed_tmp_reaper",
                "status": "blocked",
                "reasons": ["blocked"],
            },
        ),
        top_rows=(
            {
                "owner": "workspace_cleanup_and_compact",
                "size_bytes": 54 * 1024**3,
                "path": "/tmp/ws",
                "size_state": "measured",
            },
            {
                "owner": "rust_prebuild_cache",
                "size_bytes": 12 * 1024**3,
                "path": "/tmp/cache",
                "size_state": "measured",
            },
            {
                "owner": "managed_tmp_reaper",
                "size_bytes": 4 * 1024**3,
                "path": "/tmp/managed",
                "size_state": "measured",
            },
        ),
        report=report,
    )
    assert "recovery missed" in notes[0]
    assert "9.0 GiB target" in notes[0]
    assert notes[1] == "Reclaimed: 97.0 KiB"
    assert "managed_tmp_reaper incomplete×1" in notes[4]
    assert "managed_tmp_reaper blocked×1" in notes[4]
    unreaped = notes[5]
    assert "workspace_cleanup_and_compact" in unreaped
    assert "sase workspace cleanup --stale; sase workspace compact" in unreaped
    assert "rust_prebuild_cache" in unreaped
    assert "no reclaim command" in unreaped
    assert "managed_tmp_reaper" not in unreaped.split(":", 1)[1]


def test_filesystem_id_and_keys_are_episode_scoped() -> None:
    fs_id = filesystem_id({"label": "managed_tmp", "path": "/tmp/x"})
    assert fs_id == "managed_tmp"
    assert pressure_notice_key(fs_id, "abc") == "disk_pressure:managed_tmp:abc"
    assert (
        pressure_escalation_key(fs_id, "abc")
        == "disk_pressure:managed_tmp:abc:escalation"
    )
