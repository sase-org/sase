"""Output-contract tests for the error-digest and managed-tmp-reap chops."""

from __future__ import annotations

import importlib
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sase.chops.builtin import run_builtin_chop

from tests._axe_chop_output_contract_helpers import (
    _isolate_chop_result_file,  # noqa: F401 (registers the result-file isolation fixture)
    _write_context,
)


def test_error_digest_emits_noop_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_error_digest")

    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(
        "sys.argv",
        ["sase_chop_error_digest", "--context", str(context_path)],
    )
    monkeypatch.setattr(script, "read_errors", lambda: [])
    monkeypatch.setattr(script, "read_last_error_digest_ts", lambda: None)
    notify = Mock()
    monkeypatch.setattr(script, "notify_axe_error_digest", notify)

    script.main()

    notify.assert_not_called()
    out = capsys.readouterr().out
    assert "error_digest:" in out
    assert "errors_total=0" in out
    assert "recent=0" in out
    assert "notified=0" in out
    assert "reason=no_recent_errors" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["schema_version"] == 1
    assert result["status"] == "no_op"
    assert result["reason"] == "no_recent_errors"
    assert result["counters"] == {
        "errors_total": 0,
        "notified": 0,
        "recent": 0,
    }


def test_error_digest_emits_action_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_error_digest")

    errors = [
        {"timestamp": "2099-05-12T10:00:00-04:00", "message": "older"},
        {"timestamp": "2099-05-12T10:05:00-04:00", "message": "newer"},
    ]
    written: list[str] = []
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(
        "sys.argv",
        ["sase_chop_error_digest", "--context", str(context_path)],
    )
    monkeypatch.setattr(script, "read_errors", lambda: errors)
    monkeypatch.setattr(
        script,
        "read_last_error_digest_ts",
        lambda: "2026-05-12T09:00:00-04:00",
    )
    notify = Mock()
    monkeypatch.setattr(script, "notify_axe_error_digest", notify)
    monkeypatch.setattr(script, "write_last_error_digest_ts", written.append)

    script.main()

    notify.assert_called_once_with(errors)
    assert written == ["2099-05-12T10:05:00-04:00"]
    out = capsys.readouterr().out
    assert "error_digest:" in out
    assert "errors_total=2" in out
    assert "recent=2" in out
    assert "notified=2" in out
    assert "newest=2099-05-12T10:05:00-04:00" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["reason"] is None
    assert result["counters"] == {
        "errors_total": 2,
        "notified": 2,
        "recent": 2,
    }


def _pin_reap_free_space(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep real host free space from leaking pressure counters into the contract."""
    from sase.core import managed_tmp_reaper

    monkeypatch.setattr(
        "sase.scripts.sase_chop_managed_tmp_reap.filesystem_pressure_policy",
        lambda **_kwargs: SimpleNamespace(
            free_bytes=64 * 1024**3,
            warn_free_bytes=3 * 1024**3,
        ),
    )
    monkeypatch.setattr(
        "sase.scripts.sase_chop_managed_tmp_reap.reap_managed_tmpdir",
        lambda **kwargs: managed_tmp_reaper.reap_managed_tmpdir(**kwargs),
    )


def _fake_managed_reap_result(
    root: Path,
    **overrides: object,
) -> SimpleNamespace:
    values: dict[str, object] = {
        "root": root,
        "scanned": 0,
        "selected": 0,
        "removed": 0,
        "selected_by_subdir": {},
        "removed_by_subdir": {},
        "selected_bytes": 0,
        "removed_bytes": 0,
        "ordinary_selected": 0,
        "ordinary_removed": 0,
        "ordinary_reclaimable_bytes": 0,
        "ordinary_reclaimed_bytes": 0,
        "launch_selected": 0,
        "launch_removed": 0,
        "launch_reclaimable_bytes": 0,
        "launch_reclaimed_bytes": 0,
        "dead_launch_scanned": 0,
        "dead_launch_selected": 0,
        "dead_launch_removed": 0,
        "dead_launch_reclaimable_bytes": 0,
        "dead_launch_reclaimed_bytes": 0,
        "dead_launch_preserved_live": 0,
        "dead_launch_preserved_incomplete": 0,
        "dead_launch_observer": "procfs",
        "pressure_selected": 0,
        "pressure_removed": 0,
        "pressure_reclaimable_bytes": 0,
        "pressure_reclaimed_bytes": 0,
        "pressure_trigger": None,
        "pressure_available_bytes": None,
        "pressure_recovery_available_bytes": None,
        "pressure_effective_min_age_seconds": None,
        "deindexed": 0,
        "capped": False,
        "skipped": 0,
        "failed": 0,
        "incomplete_observations": 0,
        "skip_reasons": (),
        "removal_errors": (),
        "describe": lambda: "nothing stale under managed",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _prepare_managed_tmp_reap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reap_result: SimpleNamespace,
) -> tuple[Path, Path]:
    script = importlib.import_module("sase.scripts.sase_chop_managed_tmp_reap")
    managed_root = tmp_path / "managed"
    managed_root.mkdir()
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(
        "sase.core.managed_tmp_reaper.managed_tmpdir_root", lambda: managed_root
    )
    monkeypatch.setattr(
        script,
        "effective_managed_tmp_roots",
        lambda **_kwargs: [managed_root],
    )
    monkeypatch.setattr(
        script,
        "filesystem_pressure_policy",
        lambda **_kwargs: SimpleNamespace(
            free_bytes=64 * 1024**3,
            warn_free_bytes=3 * 1024**3,
        ),
    )
    monkeypatch.setattr(script, "reap_managed_tmpdir", lambda **_kwargs: reap_result)
    return result_path, context_path


def test_managed_tmp_reap_emits_noop_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    importlib.import_module("sase.scripts.sase_chop_managed_tmp_reap")

    managed_root = tmp_path / "managed"
    managed_root.mkdir()
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(
        "sase.core.managed_tmp_reaper.managed_tmpdir_root", lambda: managed_root
    )
    _pin_reap_free_space(monkeypatch)
    # The backstop is enabled by default; pin it so an ambient opt-out in
    # sase.yml cannot move the dead_launch_observer counter.
    monkeypatch.setattr(
        "sase.core.managed_tmp_reaper.get_managed_tmp_dead_launch_enabled",
        lambda: True,
    )

    run_builtin_chop("managed_tmp_reap", ["--context", str(context_path)])

    out = capsys.readouterr().out
    assert "managed_tmp_reap:" in out
    assert "removed=0" in out
    assert "reason=nothing_stale" in out
    # String-valued fields ride the summary line even though counters
    # only carry ints (same as pressure_trigger).
    assert "dead_launch_observer=procfs" in out
    # Even a no-op names the root it scanned, so a stale-root miss is visible.
    assert "nothing stale under" in out
    assert str(managed_root) in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "no_op"
    assert result["reason"] == "nothing_stale"
    assert result["counters"] == {
        "capped": 0,
        "deindexed": 0,
        "dead_launch_scanned": 0,
        "dead_launch_selected": 0,
        "dead_launch_removed": 0,
        "dead_launch_reclaimable_bytes": 0,
        "dead_launch_reclaimed_bytes": 0,
        "dead_launch_preserved_live": 0,
        "dead_launch_preserved_incomplete": 0,
        "failed": 0,
        "incomplete_observations": 0,
        "launch_reclaimable_bytes": 0,
        "launch_reclaimed_bytes": 0,
        "launch_removed": 0,
        "launch_selected": 0,
        "ordinary_reclaimable_bytes": 0,
        "ordinary_reclaimed_bytes": 0,
        "ordinary_removed": 0,
        "ordinary_selected": 0,
        "pressure_reclaimable_bytes": 0,
        "pressure_reclaimed_bytes": 0,
        "pressure_removed": 0,
        "pressure_selected": 0,
        "removed": 0,
        "removed_bytes": 0,
        "roots_scanned": 1,
        "scanned": 0,
        "selected": 0,
        "selected_bytes": 0,
        "skipped": 0,
        "subdirs": 0,
    }


def test_managed_tmp_reap_emits_action_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    importlib.import_module("sase.scripts.sase_chop_managed_tmp_reap")

    managed_root = tmp_path / "managed"
    stale = managed_root / "editors" / "note.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("scratch", encoding="utf-8")
    ancient = time.time() - 400 * 24 * 3600
    os.utime(stale, (ancient, ancient))

    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(
        "sase.core.managed_tmp_reaper.managed_tmpdir_root", lambda: managed_root
    )
    _pin_reap_free_space(monkeypatch)
    # The backstop is enabled by default; pin it so an ambient opt-out in
    # sase.yml cannot move the dead_launch_observer counter.
    monkeypatch.setattr(
        "sase.core.managed_tmp_reaper.get_managed_tmp_dead_launch_enabled",
        lambda: True,
    )

    run_builtin_chop("managed_tmp_reap", ["--context", str(context_path)])

    assert not stale.exists()
    out = capsys.readouterr().out
    assert "reclaimed 1 entries" in out
    assert "removed=1" in out
    assert "subdirs=1" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["reason"] is None
    assert result["counters"] == {
        "capped": 0,
        "deindexed": 0,
        "dead_launch_scanned": 0,
        "dead_launch_selected": 0,
        "dead_launch_removed": 0,
        "dead_launch_reclaimable_bytes": 0,
        "dead_launch_reclaimed_bytes": 0,
        "dead_launch_preserved_live": 0,
        "dead_launch_preserved_incomplete": 0,
        "failed": 0,
        "incomplete_observations": 0,
        "launch_reclaimable_bytes": 0,
        "launch_reclaimed_bytes": 0,
        "launch_removed": 0,
        "launch_selected": 0,
        "ordinary_reclaimable_bytes": 7,
        "ordinary_reclaimed_bytes": 7,
        "ordinary_removed": 1,
        "ordinary_selected": 1,
        "pressure_reclaimable_bytes": 0,
        "pressure_reclaimed_bytes": 0,
        "pressure_removed": 0,
        "pressure_selected": 0,
        "removed": 1,
        "removed_bytes": 7,
        "roots_scanned": 1,
        "scanned": 1,
        "selected": 1,
        "selected_bytes": 7,
        "skipped": 0,
        "subdirs": 1,
    }


def test_managed_tmp_reap_reports_pressure_min_age(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_managed_tmp_reap")
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    managed_root = tmp_path / "managed"
    managed_root.mkdir()
    monkeypatch.setattr(
        script,
        "effective_managed_tmp_roots",
        lambda *, effective_root, sase_home: [managed_root],
    )
    monkeypatch.setattr(
        script,
        "reap_managed_tmpdir",
        lambda **_kwargs: SimpleNamespace(
            root=managed_root,
            scanned=3,
            selected=1,
            removed=1,
            selected_by_subdir={"cargo-targets": 1},
            removed_by_subdir={"cargo-targets": 1},
            selected_bytes=4096,
            removed_bytes=4096,
            ordinary_selected=0,
            ordinary_removed=0,
            ordinary_reclaimable_bytes=0,
            ordinary_reclaimed_bytes=0,
            launch_selected=0,
            launch_removed=0,
            launch_reclaimable_bytes=0,
            launch_reclaimed_bytes=0,
            dead_launch_scanned=0,
            dead_launch_selected=0,
            dead_launch_removed=0,
            dead_launch_reclaimable_bytes=0,
            dead_launch_reclaimed_bytes=0,
            dead_launch_preserved_live=0,
            dead_launch_preserved_incomplete=0,
            dead_launch_observer="procfs",
            pressure_selected=1,
            pressure_removed=1,
            pressure_reclaimable_bytes=4096,
            pressure_reclaimed_bytes=4096,
            pressure_trigger="free_space",
            pressure_available_bytes=8 * 1024,
            pressure_recovery_available_bytes=16 * 1024,
            pressure_effective_min_age_seconds=3600.0,
            skipped=0,
            failed=0,
            incomplete_observations=0,
            deindexed=0,
            capped=False,
            describe=lambda: "reclaimed 1 entries under managed",
        ),
    )

    run_builtin_chop("managed_tmp_reap", ["--context", str(context_path)])

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["counters"]["pressure_min_age_seconds"] == 3600.0


def test_managed_tmp_reap_reports_removal_failures_and_logs_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    managed_root = tmp_path / "managed"
    reap_result = _fake_managed_reap_result(
        managed_root,
        failed=1,
        removal_errors=tuple(f"remove error {index}" for index in range(6)),
        skip_reasons=tuple(f"skip reason {index}" for index in range(6)),
        describe=lambda: "failed to remove under managed",
    )
    result_path, context_path = _prepare_managed_tmp_reap(
        monkeypatch, tmp_path, reap_result
    )

    run_builtin_chop("managed_tmp_reap", ["--context", str(context_path)])

    stderr = capsys.readouterr().err
    assert "managed_tmp_reap removal error: remove error 0" in stderr
    assert "managed_tmp_reap removal error: remove error 4" in stderr
    assert "remove error 5" not in stderr
    assert "managed_tmp_reap skipped: skip reason 0" in stderr
    assert "managed_tmp_reap skipped: skip reason 4" in stderr
    assert "skip reason 5" not in stderr
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "check_error"
    assert result["reason"] == "removal_failed"
    assert result["counters"]["failed"] == 1


def test_managed_tmp_reap_does_not_error_on_incomplete_observation_alone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    managed_root = tmp_path / "managed"
    reap_result = _fake_managed_reap_result(
        managed_root,
        incomplete_observations=1,
        skip_reasons=("observer incomplete",),
    )
    result_path, context_path = _prepare_managed_tmp_reap(
        monkeypatch, tmp_path, reap_result
    )

    run_builtin_chop("managed_tmp_reap", ["--context", str(context_path)])

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "no_op"
    assert result["reason"] == "nothing_stale"
    assert result["counters"]["failed"] == 0
    assert result["counters"]["incomplete_observations"] == 1


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
) -> tuple[Path, Path, dict[str, object], list[str], list[tuple[object, ...]]]:
    script = importlib.import_module("sase.scripts.sase_chop_disk_pressure")

    managed_root = tmp_path / "managed"
    sase_home = tmp_path / ".sase"
    managed_root.mkdir(parents=True)
    sase_home.mkdir(parents=True)
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    captured: dict[str, object] = {}
    events: list[str] = []
    notifications: list[tuple[object, ...]] = []

    monkeypatch.setattr(script, "managed_tmpdir_root", lambda: managed_root)
    monkeypatch.setattr(script, "sase_home", lambda: sase_home)
    monkeypatch.setattr(
        script, "collect_disk_footprint", lambda: SimpleNamespace(rows=())
    )
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
                "path": str(sase_home),
                "measurement_path": str(sase_home),
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
            steps=(object(),) * len(owners),
        )

    monkeypatch.setattr(script, "run_disk_reap", run_disk_reap)
    monkeypatch.setattr(
        script,
        "_statvfs_available_bytes",
        lambda _path: available_after_bytes,
    )

    def notify(*args: object, **kwargs: object) -> None:
        events.append("notify")
        notifications.append((*args, kwargs))
        if isinstance(notification, Exception):
            raise notification

    monkeypatch.setattr(script, "notify_workflow_complete", notify)
    return result_path, context_path, captured, events, notifications


def test_disk_pressure_reaps_before_one_outcome_notification(
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
    )

    run_builtin_chop("disk_pressure", ["--context", str(context_path)])

    assert captured["filesystem_available_bytes"] == 2 * 1024**3
    assert captured["managed_tmp_pressure_min_available_bytes"] == 5 * 1024**3
    assert captured["managed_tmp_pressure_recovery_available_bytes"] == 5 * 1024**3
    assert events == ["reap", "notify"]
    assert len(notifications) == 1
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
    assert "Recovery target:" in str(notifications[0][3])


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

    assert events == ["reap", "notify"]
    stderr = capsys.readouterr().err
    assert "disk_pressure notification failed: ValueError:" in stderr
    assert "[Errno 28] No space left on device" in stderr
    assert len(stderr.splitlines()) == 1
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
