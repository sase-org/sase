"""Stale agent-name registry temp-file sweep tests."""

from __future__ import annotations

import os
import time
from pathlib import Path

from sase.agent.names._registry_store import (
    sweep_stale_registry_tmp_files,
    write_registry,
)
from sase.core.disk_footprint_reap_registry_tmps import (
    REGISTRY_TMP_SWEEP_OWNER,
    registry_tmp_reap_step,
)


def _write_tmp(path: Path, name: str, *, age_seconds: float, size: int = 4) -> Path:
    tmp = path / name
    tmp.write_bytes(b"x" * size)
    old = time.time() - age_seconds
    os.utime(tmp, (old, old))
    return tmp


def test_sweep_removes_stale_tmp_and_keeps_fresh(tmp_path: Path) -> None:
    stale = _write_tmp(
        tmp_path, ".agent_name_registry.json.abc123.tmp", age_seconds=3600
    )
    fresh = _write_tmp(tmp_path, ".agent_name_registry.json.def456.tmp", age_seconds=60)
    live = tmp_path / "agent_name_registry.json"
    live.write_text("{}", encoding="utf-8")

    result = sweep_stale_registry_tmp_files(live, max_age_seconds=600, max_removals=200)

    assert not stale.exists()
    assert fresh.exists()
    assert live.exists()
    assert result.removed == 1
    assert result.selected == 1
    assert result.reclaimed_bytes == 4
    assert not result.capped


def test_sweep_ignores_other_files_and_symlinks(tmp_path: Path) -> None:
    (tmp_path / "agent_name_registry.json").write_text("{}", encoding="utf-8")
    (tmp_path / "agent_name_registry.json.bak").write_text("keep", encoding="utf-8")
    (tmp_path / ".agent_name_registry.json.notmp").write_text("keep", encoding="utf-8")
    target = tmp_path / "real.tmp"
    target.write_bytes(b"keep")
    link = tmp_path / ".agent_name_registry.json.link.tmp"
    link.symlink_to(target)
    old = time.time() - 3600
    os.utime(link, (old, old), follow_symlinks=False)

    result = sweep_stale_registry_tmp_files(
        tmp_path / "agent_name_registry.json", max_age_seconds=600, max_removals=200
    )

    assert result.removed == 0
    assert target.exists()
    assert (tmp_path / "agent_name_registry.json.bak").exists()


def test_sweep_preview_counts_without_removing(tmp_path: Path) -> None:
    stale = _write_tmp(
        tmp_path, ".agent_name_registry.json.abc123.tmp", age_seconds=3600
    )

    result = sweep_stale_registry_tmp_files(
        tmp_path / "agent_name_registry.json",
        max_age_seconds=600,
        max_removals=200,
        apply=False,
    )

    assert stale.exists()
    assert result.removed == 0
    assert result.selected == 1
    assert result.paths == (str(stale),)


def test_sweep_budget_caps_oldest_first(tmp_path: Path) -> None:
    now = time.time()
    olds: list[Path] = []
    for index in range(3):
        tmp = tmp_path / f".agent_name_registry.json.tmp{index}.tmp"
        tmp.write_bytes(b"x")
        old = now - 3600 - index
        os.utime(tmp, (old, old))
        olds.append(tmp)

    result = sweep_stale_registry_tmp_files(
        tmp_path / "agent_name_registry.json",
        max_age_seconds=600,
        max_removals=2,
        now=now,
    )

    assert result.removed == 2
    assert result.capped is True
    assert not olds[2].exists()
    assert not olds[1].exists()
    assert olds[0].exists()


def test_sweep_missing_dir_reports_error(tmp_path: Path) -> None:
    result = sweep_stale_registry_tmp_files(
        tmp_path / "nope" / "agent_name_registry.json",
        max_age_seconds=600,
        max_removals=200,
    )

    assert result.errors
    assert result.removed == 0


def test_write_registry_sweeps_its_own_stale_tmps(tmp_path: Path) -> None:
    path = tmp_path / "agent_name_registry.json"
    stale = _write_tmp(
        tmp_path, ".agent_name_registry.json.abc123.tmp", age_seconds=3600, size=8
    )
    fresh = _write_tmp(
        tmp_path, ".agent_name_registry.json.def456.tmp", age_seconds=60, size=8
    )

    write_registry(path, {"entries": {}})

    assert not stale.exists()
    assert fresh.exists()
    assert path.exists()


def test_step_preview_and_apply(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "agent_name_registry.json"
    path.write_text("{}", encoding="utf-8")
    stale = _write_tmp(
        tmp_path, ".agent_name_registry.json.abc123.tmp", age_seconds=3600
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_registry_tmps.registry_path",
        lambda: path,
    )

    preview = registry_tmp_reap_step(apply=False)

    assert preview.owner == REGISTRY_TMP_SWEEP_OWNER
    assert preview.mode == "dry_run"
    assert "would remove 1 stale registry temp file(s)" in preview.summary
    assert stale.exists()

    applied = registry_tmp_reap_step(apply=True)

    assert applied.mode == "apply"
    assert applied.changed is True
    assert not stale.exists()
