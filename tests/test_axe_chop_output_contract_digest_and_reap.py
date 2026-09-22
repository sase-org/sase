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

    run_builtin_chop("managed_tmp_reap", ["--context", str(context_path)])

    out = capsys.readouterr().out
    assert "managed_tmp_reap:" in out
    assert "removed=0" in out
    assert "reason=nothing_stale" in out
    # Even a no-op names the root it scanned, so a stale-root miss is visible.
    assert "nothing stale under" in out
    assert str(managed_root) in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "no_op"
    assert result["reason"] == "nothing_stale"
    assert result["counters"] == {
        "capped": 0,
        "deindexed": 0,
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
    monkeypatch.setattr(
        script,
        "reap_managed_tmpdir",
        lambda **_kwargs: SimpleNamespace(
            scanned=3,
            selected=1,
            removed=1,
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


def test_disk_pressure_chop_routes_managed_tmp_filesystem_to_reap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_disk_pressure")
    from sase.core import disk_pressure

    managed_root = tmp_path / "managed"
    sase_home = tmp_path / ".sase"
    managed_root.mkdir()
    sase_home.mkdir()
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    captured: dict[str, object] = {}

    monkeypatch.setattr(script, "managed_tmpdir_root", lambda: managed_root)
    monkeypatch.setattr(script, "sase_home", lambda: sase_home)
    monkeypatch.setattr(
        script, "collect_disk_footprint", lambda: SimpleNamespace(rows=())
    )
    monkeypatch.setattr(
        disk_pressure,
        "_filesystem_identity",
        lambda path, *, filesystem_identity_fn=None: str(path),
    )

    def disk_usage(path: str) -> SimpleNamespace:
        if path == str(managed_root):
            return SimpleNamespace(
                total=100 * 1024**3, used=95 * 1024**3, free=2 * 1024**3
            )
        if path == str(sase_home):
            return SimpleNamespace(
                total=100 * 1024**3, used=20 * 1024**3, free=80 * 1024**3
            )
        raise AssertionError(path)

    def run_disk_reap(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(changed=False, failed=True, steps=(object(),))

    monkeypatch.setattr(script.shutil, "disk_usage", disk_usage)
    monkeypatch.setattr(script, "run_disk_reap", run_disk_reap)

    run_builtin_chop("disk_pressure", ["--context", str(context_path)])

    assert captured["filesystem_available_bytes"] == 2 * 1024**3
    assert captured["managed_tmp_pressure_min_available_bytes"] == 5 * 1024**3
    assert captured["managed_tmp_pressure_recovery_available_bytes"] == 5 * 1024**3
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["counters"]["observations"] == 2
    assert result["counters"]["failed"] == 1
