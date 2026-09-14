"""Pressure-triggered reaping semantics for the managed-tmp reaper."""

from __future__ import annotations

import os
from pathlib import Path

from sase.core.managed_tmp_reaper import BUILD_SCRATCH_HORIZON_SECONDS
from tests._managed_tmp_reaper_helpers import (
    DAY,
    HOUR,
    NOW,
    _aged_dir,
    reap_managed_tmpdir,
)


def test_pressure_reaping_prunes_large_build_scratch_before_horizon(
    tmp_path: Path,
) -> None:
    old_large = _aged_dir(
        tmp_path,
        "cargo-targets/run-old",
        age_seconds=DAY,
        size_bytes=8 * 1024,
    )
    old_small = _aged_dir(
        tmp_path,
        "cargo-targets/run-small",
        age_seconds=DAY,
        size_bytes=512,
    )
    fresh_large = _aged_dir(
        tmp_path,
        "cargo-targets/run-live",
        age_seconds=HOUR,
        size_bytes=8 * 1024,
    )

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        pressure_max_bytes=4 * 1024,
        pressure_target_bytes=1024,
        pressure_min_age_seconds=12 * HOUR,
        pressure_min_entry_bytes=2 * 1024,
    )

    assert not old_large.exists()
    assert old_small.exists()
    assert fresh_large.exists()
    assert result.pressure_removed == 1
    assert result.pressure_reclaimed_bytes >= 8 * 1024
    assert result.removed_by_subdir == {"cargo-targets": 1}


def test_ordinary_cargo_build_dir_names_are_eligible_and_protect_fresh_descendants(
    tmp_path: Path,
) -> None:
    stale = _aged_dir(
        tmp_path,
        "build-targets/cargo-abcd1234",
        age_seconds=BUILD_SCRATCH_HORIZON_SECONDS + HOUR,
    )
    protected = _aged_dir(
        tmp_path,
        "build-targets/cargo-efgh5678",
        age_seconds=BUILD_SCRATCH_HORIZON_SECONDS + HOUR,
    )
    fresh_child = protected / "deps" / "lib.rmeta"
    fresh_child.parent.mkdir(parents=True, exist_ok=True)
    fresh_child.write_text("fresh", encoding="utf-8")
    os.utime(fresh_child, (NOW, NOW))
    unrelated = _aged_dir(
        tmp_path,
        "agent-tmp/unrelated",
        age_seconds=HOUR,
    )
    symlink = tmp_path / "build-targets" / "cargo-symlink"
    symlink.symlink_to(stale)

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert not stale.exists()
    assert protected.exists()
    assert unrelated.exists()
    assert symlink.is_symlink()
    assert result.removed_by_subdir.get("build-targets") == 1


def test_pressure_reaping_catches_legacy_build_targets_bucket(
    tmp_path: Path,
) -> None:
    old_large = _aged_dir(
        tmp_path,
        "build-targets/run-old",
        age_seconds=DAY,
        size_bytes=8 * 1024,
    )

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        pressure_max_bytes=4 * 1024,
        pressure_target_bytes=1024,
        pressure_min_age_seconds=12 * HOUR,
        pressure_min_entry_bytes=2 * 1024,
    )

    assert not old_large.exists()
    assert result.pressure_removed == 1
    assert result.removed_by_subdir == {"build-targets": 1}


def test_pressure_reaping_catches_large_top_level_target_residue(
    tmp_path: Path,
) -> None:
    old_target = _aged_dir(
        tmp_path,
        "sase-yh4-cargo-target",
        age_seconds=DAY,
        size_bytes=8 * 1024,
    )

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        pressure_max_bytes=4 * 1024,
        pressure_target_bytes=1024,
        pressure_min_age_seconds=12 * HOUR,
        pressure_min_entry_bytes=2 * 1024,
    )

    assert not old_target.exists()
    assert result.pressure_removed == 1
    assert result.removed_by_subdir == {"<root>": 1}


def test_pressure_reaping_uses_low_free_space_below_root_ceiling(
    tmp_path: Path,
) -> None:
    recent_large = _aged_dir(
        tmp_path,
        "cargo-targets/run-recent",
        age_seconds=2 * HOUR,
        size_bytes=8 * 1024,
    )

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        pressure_max_bytes=64 * 1024,
        pressure_target_bytes=32 * 1024,
        pressure_min_available_bytes=10 * 1024,
        pressure_recovery_available_bytes=16 * 1024,
        pressure_min_age_seconds=12 * HOUR,
        pressure_min_entry_bytes=2 * 1024,
        filesystem_available_bytes=8 * 1024,
    )

    assert not recent_large.exists()
    assert result.pressure_removed == 1
    assert result.pressure_trigger == "free_space"
    assert result.pressure_available_bytes == 8 * 1024
    assert result.pressure_recovery_available_bytes == 16 * 1024
    assert result.pressure_effective_min_age_seconds == HOUR


def test_pressure_reaping_uses_low_free_space_age_when_size_also_triggers(
    tmp_path: Path,
) -> None:
    recent_large = _aged_dir(
        tmp_path,
        "cargo-targets/run-recent",
        age_seconds=2 * HOUR,
        size_bytes=8 * 1024,
    )

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        pressure_max_bytes=4 * 1024,
        pressure_target_bytes=1024,
        pressure_min_available_bytes=10 * 1024,
        pressure_recovery_available_bytes=16 * 1024,
        pressure_min_age_seconds=12 * HOUR,
        pressure_min_entry_bytes=2 * 1024,
        filesystem_available_bytes=8 * 1024,
    )

    assert not recent_large.exists()
    assert result.pressure_removed == 1
    assert result.pressure_trigger == "size_and_free_space"
    assert result.pressure_effective_min_age_seconds == HOUR


def test_pressure_reaping_keeps_recent_targets_when_free_space_is_ample(
    tmp_path: Path,
) -> None:
    recent_large = _aged_dir(
        tmp_path,
        "cargo-targets/run-recent",
        age_seconds=2 * HOUR,
        size_bytes=8 * 1024,
    )

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        pressure_max_bytes=4 * 1024,
        pressure_target_bytes=1024,
        pressure_min_available_bytes=10 * 1024,
        pressure_recovery_available_bytes=16 * 1024,
        pressure_min_age_seconds=12 * HOUR,
        pressure_min_entry_bytes=2 * 1024,
        filesystem_available_bytes=64 * 1024,
    )

    assert recent_large.exists()
    assert result.pressure_removed == 0
    assert result.pressure_trigger == "size"
    assert result.pressure_effective_min_age_seconds == 12 * HOUR


def test_low_free_space_pressure_age_still_protects_fresh_descendant(
    tmp_path: Path,
) -> None:
    target = _aged_dir(
        tmp_path,
        "cargo-targets/run-live",
        age_seconds=2 * HOUR,
        size_bytes=8 * 1024,
    )
    fresh_child = target / "deps" / "lib.rmeta"
    fresh_child.parent.mkdir(parents=True, exist_ok=True)
    fresh_child.write_text("fresh", encoding="utf-8")
    fresh_stamp = NOW - (0.5 * HOUR)
    os.utime(fresh_child, (fresh_stamp, fresh_stamp))

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        pressure_max_bytes=4 * 1024,
        pressure_target_bytes=1024,
        pressure_min_available_bytes=10 * 1024,
        pressure_recovery_available_bytes=16 * 1024,
        pressure_min_age_seconds=12 * HOUR,
        pressure_min_entry_bytes=2 * 1024,
        filesystem_available_bytes=8 * 1024,
    )

    assert target.exists()
    assert fresh_child.exists()
    assert result.pressure_removed == 0
    assert result.pressure_trigger == "size_and_free_space"
    assert result.pressure_effective_min_age_seconds == HOUR


def test_pressure_reaping_stops_at_free_space_recovery_threshold(
    tmp_path: Path,
) -> None:
    largest = _aged_dir(
        tmp_path,
        "cargo-targets/run-largest",
        age_seconds=DAY,
        size_bytes=8 * 1024,
    )
    smaller = _aged_dir(
        tmp_path,
        "cargo-targets/run-smaller",
        age_seconds=DAY,
        size_bytes=4 * 1024,
    )

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        pressure_max_bytes=64 * 1024,
        pressure_target_bytes=32 * 1024,
        pressure_min_available_bytes=10 * 1024,
        pressure_recovery_available_bytes=15 * 1024,
        pressure_min_age_seconds=12 * HOUR,
        pressure_min_entry_bytes=2 * 1024,
        filesystem_available_bytes=8 * 1024,
    )

    assert not largest.exists()
    assert smaller.exists()
    assert result.pressure_removed == 1
    assert result.pressure_trigger == "free_space"


def test_pressure_reaping_preserves_unknown_bucket_with_fresh_child(
    tmp_path: Path,
) -> None:
    unknown_bucket = tmp_path / "unknown-bucket"
    fresh_payload = unknown_bucket / "fresh-handoff" / "payload.bin"
    fresh_payload.parent.mkdir(parents=True)
    with fresh_payload.open("wb") as handle:
        handle.truncate(4 * 1024)
    fresh_stamp = NOW - HOUR
    stale_stamp = NOW - (DAY + HOUR)
    os.utime(fresh_payload, (fresh_stamp, fresh_stamp))
    os.utime(unknown_bucket, (stale_stamp, stale_stamp))

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        horizons={},
        pressure_max_bytes=100,
        pressure_target_bytes=50,
        pressure_min_age_seconds=12 * HOUR,
        pressure_min_entry_bytes=1,
    )

    assert unknown_bucket.is_dir()
    assert fresh_payload.exists()
    assert result.pressure_trigger == "size"
    assert result.pressure_removed == 0
    assert result.removed == 0


def test_pressure_reaping_skips_generic_agent_tmp_and_handoff(
    tmp_path: Path,
) -> None:
    agent_tmp = _aged_dir(
        tmp_path,
        "agent-tmp/run-old",
        age_seconds=2 * HOUR,
        size_bytes=8 * 1024,
    )
    handoff = _aged_dir(
        tmp_path,
        "handoff/run-old",
        age_seconds=2 * HOUR,
        size_bytes=8 * 1024,
    )

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        pressure_max_bytes=4 * 1024,
        pressure_target_bytes=1024,
        pressure_min_age_seconds=HOUR,
        pressure_min_entry_bytes=2 * 1024,
    )

    assert agent_tmp.exists()
    assert handoff.exists()
    assert result.pressure_trigger == "size"
    assert result.pressure_removed == 0
    assert result.removed == 0


def test_pressure_reaping_preserves_build_tree_with_fresh_descendant(
    tmp_path: Path,
) -> None:
    build = tmp_path / "cargo-targets" / "run-live"
    fresh_payload = build / "debug" / "incremental" / "fresh.bin"
    fresh_payload.parent.mkdir(parents=True)
    with fresh_payload.open("wb") as handle:
        handle.truncate(8 * 1024)
    old_state = build / "state.json"
    old_state.write_text("{}", encoding="utf-8")
    fresh_stamp = NOW - HOUR
    stale_stamp = NOW - DAY
    os.utime(fresh_payload, (fresh_stamp, fresh_stamp))
    os.utime(old_state, (stale_stamp, stale_stamp))
    os.utime(fresh_payload.parent, (stale_stamp, stale_stamp))
    os.utime(fresh_payload.parent.parent, (stale_stamp, stale_stamp))
    os.utime(build, (stale_stamp, stale_stamp))

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        pressure_max_bytes=4 * 1024,
        pressure_target_bytes=1024,
        pressure_min_age_seconds=12 * HOUR,
        pressure_min_entry_bytes=2 * 1024,
    )

    assert build.exists()
    assert fresh_payload.exists()
    assert result.pressure_trigger == "size"
    assert result.pressure_removed == 0
    assert result.removed == 0
