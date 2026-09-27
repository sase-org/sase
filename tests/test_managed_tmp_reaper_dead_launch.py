"""Dead-launch backstop and liveness-aware pressure for the managed-tmp reaper."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest

from tests._managed_tmp_reaper_helpers import (
    DAY,
    HOUR,
    NOW,
    _aged_dir,
    reap_managed_tmpdir,
)

GRACE = 2 * HOUR


def _empty_proc_root(parent: Path) -> Path:
    proc_root = parent / "proc"
    proc_root.mkdir(parents=True, exist_ok=True)
    return proc_root


def _holder_proc_root(parent: Path, candidate: Path) -> Path:
    proc_root = _empty_proc_root(parent)
    pid_dir = proc_root / "4242"
    pid_dir.mkdir(parents=True, exist_ok=True)
    (pid_dir / "environ").write_bytes(f"TMPDIR={candidate}\0".encode())
    return proc_root


def _incomplete_proc_root(parent: Path) -> Path:
    proc_root = _empty_proc_root(parent)
    btime = time.time() - 1000.0
    (proc_root / "stat").write_text(
        f"cpu  0 0 0 0 0 0 0 0 0 0\nbtime {int(btime)}\n", encoding="utf-8"
    )
    pid_dir = proc_root / "9999"
    pid_dir.mkdir(parents=True, exist_ok=True)
    # environ as a directory reads as an error, like EACCES on a
    # non-dumpable process; starttime far in the future keeps the
    # pre-launch exemption from applying.
    (pid_dir / "environ").mkdir()
    ticks = int(10**7 * os.sysconf("SC_CLK_TCK"))
    fields = ["R", "1"] + ["0"] * 17 + [str(ticks)]
    (pid_dir / "stat").write_text(
        f"1 (fake-proc) {' '.join(fields)}\n", encoding="utf-8"
    )
    return proc_root


def _dead_launch_kwargs(proc_root: Path) -> dict[str, Any]:
    return {
        "age_reap": False,
        "pressure_reap": False,
        "dead_launch_enabled": True,
        "dead_launch_grace_seconds": GRACE,
        "dead_launch_proc_root": proc_root,
    }


def test_dead_launch_removes_unheld_entry_past_grace(tmp_path: Path) -> None:
    proc_root = _empty_proc_root(tmp_path)
    dead = _aged_dir(
        tmp_path, "cargo-targets/dead-key", age_seconds=3 * HOUR, size_bytes=256
    )
    young = _aged_dir(
        tmp_path, "cargo-targets/young-key", age_seconds=HOUR, size_bytes=256
    )

    result = reap_managed_tmpdir(tmp_path, now=NOW, **_dead_launch_kwargs(proc_root))

    assert not dead.exists()
    assert young.exists()
    assert result.dead_launch_scanned == 2
    assert result.dead_launch_selected == 1
    assert result.dead_launch_removed == 1
    # 256-byte payload plus the helper's 2-byte state.json.
    assert result.dead_launch_reclaimable_bytes == 258
    assert result.dead_launch_reclaimed_bytes == 258
    assert result.dead_launch_preserved_live == 0
    assert result.dead_launch_preserved_incomplete == 0
    assert result.dead_launch_observer == "procfs"
    assert result.selected == 1
    assert result.removed == 1
    assert result.selected_by_subdir == {"cargo-targets": 1}


def test_dead_launch_keeps_held_entry(tmp_path: Path) -> None:
    held = _aged_dir(
        tmp_path, "agent-tmp/held-key", age_seconds=3 * HOUR, size_bytes=64
    )
    proc_root = _holder_proc_root(tmp_path, held)

    result = reap_managed_tmpdir(tmp_path, now=NOW, **_dead_launch_kwargs(proc_root))

    assert held.exists()
    assert result.dead_launch_selected == 0
    assert result.dead_launch_removed == 0
    assert result.dead_launch_preserved_live == 1
    assert result.skipped == 1
    assert any("held by a live process" in reason for reason in result.skip_reasons)


def test_dead_launch_keeps_incomplete_observation(tmp_path: Path) -> None:
    proc_root = _incomplete_proc_root(tmp_path)
    stale = _aged_dir(
        tmp_path, "cargo-targets/stale-key", age_seconds=3 * HOUR, size_bytes=64
    )

    result = reap_managed_tmpdir(tmp_path, now=NOW, **_dead_launch_kwargs(proc_root))

    assert stale.exists()
    assert result.dead_launch_selected == 0
    assert result.dead_launch_removed == 0
    assert result.dead_launch_preserved_incomplete == 1
    assert result.incomplete_observations == 1


def test_dead_launch_unobservable_skips(tmp_path: Path) -> None:
    stale = _aged_dir(
        tmp_path, "cargo-targets/stale-key", age_seconds=3 * HOUR, size_bytes=64
    )

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        **_dead_launch_kwargs(tmp_path / "no-such-proc"),
    )

    assert stale.exists()
    assert result.dead_launch_observer == "unobservable"
    assert result.dead_launch_scanned == 1
    assert result.dead_launch_selected == 0
    assert result.dead_launch_removed == 0


def test_dead_launch_respects_removal_budget(tmp_path: Path) -> None:
    proc_root = _empty_proc_root(tmp_path)
    largest = _aged_dir(
        tmp_path, "cargo-targets/largest", age_seconds=3 * HOUR, size_bytes=8192
    )
    smaller = _aged_dir(
        tmp_path, "cargo-targets/smaller", age_seconds=3 * HOUR, size_bytes=4096
    )

    result = reap_managed_tmpdir(
        tmp_path, now=NOW, max_removals=1, **_dead_launch_kwargs(proc_root)
    )

    assert not largest.exists()
    assert smaller.exists()
    assert result.dead_launch_selected == 1
    assert result.dead_launch_removed == 1
    assert result.capped


def test_dead_launch_disabled_keeps_entry(tmp_path: Path) -> None:
    proc_root = _empty_proc_root(tmp_path)
    stale = _aged_dir(
        tmp_path, "cargo-targets/stale-key", age_seconds=3 * HOUR, size_bytes=64
    )

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        age_reap=False,
        pressure_reap=False,
        dead_launch_enabled=False,
        dead_launch_grace_seconds=GRACE,
        dead_launch_proc_root=proc_root,
    )

    assert stale.exists()
    assert result.dead_launch_observer == "disabled"
    assert result.dead_launch_selected == 0
    assert result.dead_launch_removed == 0


def test_dead_launch_config_overrides_grace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.config import core as config_core

    proc_root = _empty_proc_root(tmp_path)
    stale = _aged_dir(
        tmp_path, "cargo-targets/stale-key", age_seconds=3 * HOUR, size_bytes=64
    )

    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {"managed_tmp": {"dead_launch": {"grace_seconds": 4 * HOUR}}},
    )
    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        age_reap=False,
        pressure_reap=False,
        dead_launch_proc_root=proc_root,
    )

    assert stale.exists()
    assert result.dead_launch_selected == 0


def test_dead_launch_config_disables_backstop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.config import core as config_core

    proc_root = _empty_proc_root(tmp_path)
    stale = _aged_dir(
        tmp_path, "cargo-targets/stale-key", age_seconds=3 * HOUR, size_bytes=64
    )

    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {"managed_tmp": {"dead_launch": {"enabled": False}}},
    )
    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        age_reap=False,
        pressure_reap=False,
        dead_launch_proc_root=proc_root,
    )

    assert stale.exists()
    assert result.dead_launch_observer == "disabled"


def test_pressure_never_removes_held_entry(tmp_path: Path) -> None:
    held = _aged_dir(
        tmp_path, "cargo-targets/held-run", age_seconds=DAY, size_bytes=8192
    )
    proc_root = _holder_proc_root(tmp_path, held)

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        age_reap=False,
        pressure_max_bytes=100,
        pressure_target_bytes=50,
        pressure_min_entry_bytes=1024,
        dead_launch_enabled=True,
        dead_launch_grace_seconds=GRACE,
        dead_launch_proc_root=proc_root,
    )

    assert held.exists()
    assert result.dead_launch_preserved_live == 1
    assert result.pressure_removed == 0
    assert any("held by a live process" in reason for reason in result.skip_reasons)


def test_pressure_uses_grace_for_unheld_entry(tmp_path: Path) -> None:
    proc_root = _empty_proc_root(tmp_path)
    # Top-level build-target residue is outside the dead-launch buckets;
    # older than the grace but younger than the 12-hour pressure age, so
    # only the grace shortcut makes it removable.
    residue = _aged_dir(
        tmp_path, "core-target-old", age_seconds=3 * HOUR, size_bytes=8192
    )

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        age_reap=False,
        pressure_max_bytes=100,
        pressure_target_bytes=50,
        pressure_min_entry_bytes=1024,
        dead_launch_enabled=True,
        dead_launch_grace_seconds=GRACE,
        dead_launch_proc_root=proc_root,
    )

    assert not residue.exists()
    assert result.dead_launch_removed == 0
    assert result.pressure_removed == 1


def test_describe_reports_dead_launch(tmp_path: Path) -> None:
    proc_root = _empty_proc_root(tmp_path)
    _aged_dir(tmp_path, "cargo-targets/dead-key", age_seconds=3 * HOUR, size_bytes=256)

    result = reap_managed_tmpdir(
        tmp_path, now=NOW, apply=False, **_dead_launch_kwargs(proc_root)
    )

    assert result.describe() == (
        f"would reclaim 1 entries (258 B) under {tmp_path}: "
        "cargo-targets=1; dead_launch=1 (258 B)"
    )
