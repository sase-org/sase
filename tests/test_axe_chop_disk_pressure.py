"""Output-contract tests for the disk_pressure chop."""

from __future__ import annotations

import importlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace
import pytest

from sase.chops.builtin import run_builtin_chop
from sase.core.disk_footprint_models import DiskFootprintReport
from sase.core.disk_footprint_models import DiskFootprintRow
from sase.notifications.models import Notification

from tests._axe_chop_output_contract_helpers import (
    _isolate_chop_result_file,  # noqa: F401 (registers the result-file isolation fixture)
    _write_context,
)


def _report(*rows: DiskFootprintRow, unmeasured_owners: tuple[str, ...] = ()):
    return DiskFootprintReport(
        rows=rows,
        generated_at="2026-11-19T00:00:00+00:00",
        unmeasured_owners=unmeasured_owners,
    )


def _row(
    owner: str,
    size: int,
    *,
    path: str = "/somewhere",
    reclaim: str | None = None,
    size_state: str = "measured",
) -> DiskFootprintRow:
    return DiskFootprintRow(
        section="workspaces",
        name=owner,
        path=path,
        size_bytes=size,
        owner=owner,
        horizon="test",
        exclusive_size_bytes=size,
        size_state=size_state,
        reclaim=reclaim,
    )


def _prepare_disk_pressure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    managed_free_bytes: int = 2 * 1024**3,
    home_free_bytes: int = 80 * 1024**3,
    available_after_bytes: int = 8 * 1024**3,
    owners: tuple[dict[str, object], ...] = (),
    reclaimed_bytes: int = 0,
    notification: object | None = None,
    report: DiskFootprintReport | None = None,
    inventory: object | None = None,
    sase_home: Path | None = None,
) -> tuple[Path, Path, dict[str, object], list[str], list[tuple[object, ...]]]:
    script = importlib.import_module("sase.scripts.sase_chop_disk_pressure")

    managed_root = tmp_path / "managed"
    home = sase_home if sase_home is not None else tmp_path / ".sase"
    managed_root.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    captured: dict[str, object] = {}
    events: list[str] = []
    notifications: list[tuple[object, ...]] = []

    monkeypatch.setattr(script, "managed_tmpdir_root", lambda: managed_root)
    monkeypatch.setattr(script, "sase_home", lambda: home)
    inventory_result: object
    if inventory is not None:
        inventory_result = inventory
    elif report is not None:
        inventory_result = report
    else:
        inventory_result = SimpleNamespace(rows=())

    def collect_disk_footprint() -> object:
        events.append("inventory")
        if isinstance(inventory_result, Exception):
            raise inventory_result
        if callable(inventory_result) and not isinstance(
            inventory_result, SimpleNamespace | DiskFootprintReport
        ):
            return inventory_result()
        return inventory_result

    monkeypatch.setattr(script, "collect_disk_footprint", collect_disk_footprint)
    monkeypatch.setattr(
        script,
        "collect_filesystem_observations",
        lambda targets, **_kwargs: (
            {
                "label": "managed_tmp",
                "role": "owner",
                "path": str(managed_root),
                "measurement_path": str(managed_root),
                "total_bytes": 100 * 1024**3,
                "used_bytes": 100 * 1024**3 - managed_free_bytes,
                "free_bytes": managed_free_bytes,
            },
            {
                "label": "sase_home",
                "role": "owner",
                "path": str(home),
                "measurement_path": str(home),
                "total_bytes": 100 * 1024**3,
                "used_bytes": 100 * 1024**3 - home_free_bytes,
                "free_bytes": home_free_bytes,
            },
        ),
    )

    def run_disk_reap(**kwargs):
        events.append("reap")
        captured.update(kwargs)
        return SimpleNamespace(
            cleanup_outcome={
                "owners": list(owners),
                "known_reclaimed_bytes": reclaimed_bytes,
            },
            steps=(object(),) * max(len(owners), 1),
        )

    monkeypatch.setattr(script, "run_disk_reap", run_disk_reap)
    monkeypatch.setattr(
        script,
        "_statvfs_available_bytes",
        lambda _path: available_after_bytes,
    )

    def upsert(notification_row: Notification, **kwargs: object) -> object:
        events.append("notify")
        notifications.append((notification_row, kwargs))
        if isinstance(notification, Exception):
            raise notification
        return SimpleNamespace(action="created")

    monkeypatch.setattr(script, "upsert_notification", upsert)
    return result_path, context_path, captured, events, notifications


def test_disk_pressure_reaps_before_fail_open_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result_path, context_path, captured, events, notifications = _prepare_disk_pressure(
        monkeypatch,
        tmp_path,
        owners=(
            {
                "owner": "managed_tmp_reaper",
                "status": "failed",
                "changed": True,
            },
        ),
        reclaimed_bytes=256,
        inventory=RuntimeError("scan exploded"),
    )

    run_builtin_chop("disk_pressure", ["--context", str(context_path)])

    assert captured["filesystem_available_bytes"] == 2 * 1024**3
    assert captured["managed_tmp_pressure_min_available_bytes"] == 5 * 1024**3
    assert captured["managed_tmp_pressure_recovery_available_bytes"] == 5 * 1024**3
    assert events == ["reap", "inventory", "notify"]
    assert len(notifications) == 1
    notes = notifications[0][0].notes
    assert notes[0].startswith("SASE disk pressure:")
    assert "Attribution unavailable: RuntimeError: scan exploded" in notes
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["counters"]["observations"] == 2
    assert result["counters"]["failed"] == 1
    assert result["status"] == "check_error"
    assert result["reason"] == "cleanup_failed"
    assert result["counters"]["changed"] == 1
    assert result["counters"]["reclaimed_bytes"] == 256
    assert result["counters"]["available_after_bytes"] == 8 * 1024**3
    assert "changed_owners=managed_tmp_reaper" in result["summary"]
    assert "failed_owners=managed_tmp_reaper" in result["summary"]
    assert "Recovery:" in notes[1]


def test_disk_pressure_inventory_timeout_still_reaps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_disk_pressure")
    monkeypatch.setattr(script, "INVENTORY_TIMEOUT_SECONDS", 0.05)
    started = threading.Event()
    release = threading.Event()

    def hang() -> object:
        started.set()
        release.wait(timeout=5)
        return SimpleNamespace(rows=())

    try:
        result_path, context_path, _captured, events, notifications = (
            _prepare_disk_pressure(
                monkeypatch,
                tmp_path,
                owners=(
                    {
                        "owner": "managed_tmp_reaper",
                        "status": "success",
                        "changed": True,
                    },
                ),
                inventory=hang,
            )
        )
        run_builtin_chop("disk_pressure", ["--context", str(context_path)])
        assert started.wait(timeout=1)
        assert events[0] == "reap"
        assert "notify" in events
        assert (
            "Attribution unavailable: inventory timed out" in notifications[0][0].notes
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["status"] == "ok"
        assert result["counters"]["changed"] == 1
    finally:
        release.set()


def test_disk_pressure_notice_names_unmeasured_owners(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _result_path, context_path, _captured, _events, notifications = (
        _prepare_disk_pressure(
            monkeypatch,
            tmp_path,
            owners=(
                {
                    "owner": "managed_tmp_reaper",
                    "status": "success",
                    "changed": True,
                },
            ),
            report=_report(
                _row(
                    "workspace_cleanup_and_compact",
                    0,
                    path="/tmp/ws",
                    size_state="unmeasured",
                    reclaim="sase workspace compact",
                ),
                unmeasured_owners=("workspace_cleanup_and_compact /tmp/ws",),
            ),
        )
    )

    run_builtin_chop("disk_pressure", ["--context", str(context_path)])

    notes = notifications[0][0].notes
    assert notes[0].startswith("SASE disk pressure:")
    assert "Unmeasured owner (1): workspace_cleanup_and_compact /tmp/ws" in notes
    assert notes[0].find("Unattributed") == -1


def test_disk_pressure_missed_target_escalates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result_path, context_path, _captured, events, notifications = (
        _prepare_disk_pressure(
            monkeypatch,
            tmp_path,
            available_after_bytes=2 * 1024**3,
            reclaimed_bytes=97 * 1024,
            owners=(
                {
                    "owner": "managed_tmp_reaper",
                    "status": "incomplete",
                    "changed": True,
                    "reasons": ["incomplete"],
                },
            ),
            report=_report(
                _row(
                    "workspace_cleanup_and_compact",
                    54 * 1024**3,
                    path="/tmp/ws",
                    reclaim="sase workspace cleanup --stale; sase workspace compact",
                ),
            ),
        )
    )

    run_builtin_chop("disk_pressure", ["--context", str(context_path)])

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "check_error"
    assert result["reason"] == "recovery_blocked"
    assert [event for event in events if event == "notify"] == ["notify", "notify"]
    pressure_note, escalation = notifications
    assert pressure_note[0].dedup_key is not None
    assert pressure_note[0].dedup_key.startswith("disk_pressure:managed_tmp:")
    assert escalation[0].dedup_key == f"{pressure_note[0].dedup_key}:escalation"
    assert "recovery missed" in escalation[0].notes[0]
    assert "2.0 GiB available after vs 5.0 GiB target" in escalation[0].notes[0]
    assert "Reclaimed: 97.0 KiB" in escalation[0].notes
    assert "managed_tmp_reaper incomplete×1" in escalation[0].notes[4]
    assert "workspace_cleanup_and_compact" in escalation[0].notes[5]


def test_disk_pressure_missed_target_without_blockers_is_recovery_missed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result_path, context_path, _captured, _events, notifications = (
        _prepare_disk_pressure(
            monkeypatch,
            tmp_path,
            available_after_bytes=2 * 1024**3,
            reclaimed_bytes=256,
            owners=(
                {
                    "owner": "managed_tmp_reaper",
                    "status": "success",
                    "changed": True,
                },
            ),
        )
    )

    run_builtin_chop("disk_pressure", ["--context", str(context_path)])

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "check_error"
    assert result["reason"] == "recovery_missed"
    assert len(notifications) == 2
    assert notifications[1][0].dedup_key.endswith(":escalation")


def test_disk_pressure_second_pass_plus_ones_same_episode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / ".sase"
    first_dir = tmp_path / "pass1"
    first_dir.mkdir()
    _result_path, context_path, _captured, _events, first_notes = (
        _prepare_disk_pressure(
            monkeypatch,
            first_dir,
            sase_home=home,
            owners=(
                {
                    "owner": "managed_tmp_reaper",
                    "status": "success",
                    "changed": True,
                },
            ),
        )
    )
    run_builtin_chop("disk_pressure", ["--context", str(context_path)])
    first_key = first_notes[0][0].dedup_key

    second_dir = tmp_path / "pass2"
    second_dir.mkdir()
    _result_path, context_path, _captured, _events, second_notes = (
        _prepare_disk_pressure(
            monkeypatch,
            second_dir,
            sase_home=home,
            owners=(
                {
                    "owner": "managed_tmp_reaper",
                    "status": "success",
                    "changed": True,
                },
            ),
        )
    )
    run_builtin_chop("disk_pressure", ["--context", str(context_path)])
    assert second_notes[0][0].dedup_key == first_key
    assert second_notes[0][1]["plus_one_note"].startswith("still under pressure:")


def test_disk_pressure_space_ok_ends_episode_and_next_creates_new_row(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / ".sase"
    first_dir = tmp_path / "pass1"
    first_dir.mkdir()
    _result_path, context_path, _captured, _events, first_notes = (
        _prepare_disk_pressure(
            monkeypatch,
            first_dir,
            sase_home=home,
            owners=(
                {
                    "owner": "managed_tmp_reaper",
                    "status": "success",
                    "changed": True,
                },
            ),
        )
    )
    run_builtin_chop("disk_pressure", ["--context", str(context_path)])
    first_key = first_notes[0][0].dedup_key

    ok_dir = tmp_path / "space-ok"
    ok_dir.mkdir()
    result_path, context_path, _captured, events, notifications = (
        _prepare_disk_pressure(
            monkeypatch,
            ok_dir,
            sase_home=home,
            managed_free_bytes=80 * 1024**3,
            home_free_bytes=80 * 1024**3,
        )
    )
    run_builtin_chop("disk_pressure", ["--context", str(context_path)])
    no_pressure = json.loads(result_path.read_text(encoding="utf-8"))
    assert no_pressure["status"] == "no_op"
    assert no_pressure["reason"] == "space_ok"
    assert events == []
    assert notifications == []

    next_dir = tmp_path / "pass3"
    next_dir.mkdir()
    _result_path, context_path, _captured, _events, next_notes = _prepare_disk_pressure(
        monkeypatch,
        next_dir,
        sase_home=home,
        owners=(
            {
                "owner": "managed_tmp_reaper",
                "status": "success",
                "changed": True,
            },
        ),
    )
    run_builtin_chop("disk_pressure", ["--context", str(context_path)])
    assert next_notes[0][0].dedup_key != first_key
    assert next_notes[0][0].dedup_key.startswith("disk_pressure:managed_tmp:")


def test_disk_pressure_notification_failure_does_not_prevent_reap(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    result_path, context_path, _captured, events, _notifications = (
        _prepare_disk_pressure(
            monkeypatch,
            tmp_path,
            owners=(
                {
                    "owner": "proc_runtime",
                    "status": "success",
                    "changed": True,
                },
            ),
            notification=ValueError("[Errno 28] No space left on device"),
        )
    )

    run_builtin_chop("disk_pressure", ["--context", str(context_path)])

    assert events[:2] == ["reap", "inventory"]
    assert "notify" in events
    stderr = capsys.readouterr().err
    assert "disk_pressure notification failed: ValueError:" in stderr
    assert "[Errno 28] No space left on device" in stderr
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "check_error"
    assert result["reason"] == "notify_failed"
    assert result["counters"]["notify_failed"] == 1
    assert result["counters"]["changed"] == 1


def test_disk_pressure_persistent_pressure_after_blocked_owner_is_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result_path, context_path, _captured, _events, _notifications = (
        _prepare_disk_pressure(
            monkeypatch,
            tmp_path,
            available_after_bytes=2 * 1024**3,
            owners=(
                {
                    "owner": "managed_tmp_reaper",
                    "status": "blocked",
                    "changed": False,
                },
            ),
        )
    )

    run_builtin_chop("disk_pressure", ["--context", str(context_path)])

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "check_error"
    assert result["reason"] == "recovery_blocked"
    assert result["counters"]["blocked"] == 1


def test_disk_pressure_changed_owner_is_ok_and_space_ok_is_noop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result_path, context_path, _captured, _events, _notifications = (
        _prepare_disk_pressure(
            monkeypatch,
            tmp_path,
            owners=(
                {
                    "owner": "managed_tmp_reaper",
                    "status": "success",
                    "changed": True,
                },
            ),
        )
    )

    run_builtin_chop("disk_pressure", ["--context", str(context_path)])

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["counters"]["changed"] == 1

    result_path, context_path, _captured, events, notifications = (
        _prepare_disk_pressure(
            monkeypatch,
            tmp_path / "space-ok",
            managed_free_bytes=80 * 1024**3,
            home_free_bytes=80 * 1024**3,
        )
    )
    run_builtin_chop("disk_pressure", ["--context", str(context_path)])
    no_pressure = json.loads(result_path.read_text(encoding="utf-8"))
    assert no_pressure["status"] == "no_op"
    assert no_pressure["reason"] == "space_ok"
    assert events == []
    assert notifications == []
