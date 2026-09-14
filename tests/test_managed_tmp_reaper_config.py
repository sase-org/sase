"""Config-driven overrides and internal contract checks for the managed-tmp reaper."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests._managed_tmp_reaper_helpers import (
    DAY,
    HOUR,
    NOW,
    _aged_dir,
    _aged_file,
    reap_managed_tmpdir,
)


def test_managed_tmp_config_overrides_the_command_scratch_horizon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.config import core as config_core

    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {"managed_tmp": {"horizons": {"command_scratch_seconds": HOUR}}},
    )
    now_stale = _aged_file(tmp_path, "editors/note.md", age_seconds=2 * HOUR)

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert not now_stale.exists()
    assert result.removed == 1


def test_managed_tmp_config_overrides_pressure_thresholds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.config import core as config_core

    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {
            "managed_tmp": {
                "pressure": {
                    "max_bytes": 4 * 1024,
                    "target_bytes": 1024,
                    "min_age_seconds": 12 * HOUR,
                    "min_entry_bytes": 2 * 1024,
                }
            }
        },
    )
    old_large = _aged_dir(
        tmp_path, "cargo-targets/run-old", age_seconds=DAY, size_bytes=8 * 1024
    )

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert not old_large.exists()
    assert result.pressure_removed == 1


def test_managed_tmp_config_overrides_low_free_space_pressure_age(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.config import core as config_core

    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {
            "managed_tmp": {
                "pressure": {
                    "max_bytes": 4 * 1024,
                    "target_bytes": 1024,
                    "min_available_bytes": 10 * 1024,
                    "recovery_available_bytes": 16 * 1024,
                    "min_age_seconds": 12 * HOUR,
                    "low_free_space_min_age_seconds": 4 * HOUR,
                    "min_entry_bytes": 2 * 1024,
                }
            }
        },
    )
    recent_large = _aged_dir(
        tmp_path,
        "cargo-targets/run-recent",
        age_seconds=3 * HOUR,
        size_bytes=8 * 1024,
    )

    result = reap_managed_tmpdir(
        tmp_path,
        now=NOW,
        filesystem_available_bytes=8 * 1024,
    )

    assert recent_large.exists()
    assert result.pressure_removed == 0
    assert result.pressure_trigger == "size_and_free_space"
    assert result.pressure_effective_min_age_seconds == 4 * HOUR


def test_stale_reap_wire_schema_version_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.core.managed_tmp_reaper as reaper_module

    real_require_rust_binding = reaper_module.require_rust_binding

    def _fake_require_rust_binding(name: str):
        if name == "managed_tmp_reap_wire_schema_version":
            return lambda: 999
        return real_require_rust_binding(name)

    monkeypatch.setattr(
        reaper_module, "require_rust_binding", _fake_require_rust_binding
    )

    with pytest.raises(RuntimeError, match="stale"):
        reap_managed_tmpdir(tmp_path, now=NOW)
