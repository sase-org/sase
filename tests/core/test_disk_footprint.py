"""Tests for SASE disk-footprint inventory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sase.core.disk_footprint import collect_disk_footprint, run_disk_reap
from sase.core.disk_footprint_models import DiskReapStep
from sase.core.disk_footprint_inventory import cargo_stray_rows
from sase.core.disk_footprint_utils import InventoryScanBudget
from sase.core.disk_footprint_reap import managed_tmp_reap_step


@dataclass(frozen=True)
class _ProjectInfo:
    project: str
    project_key: str
    root_dir: str
    cleanup_ttl_days: int
    primary_workspace_dir: str | None = None
    share_git_objects: bool = True


@dataclass(frozen=True)
class _Issue:
    project: str
    message: str


@dataclass(frozen=True)
class _Inventory:
    projects: tuple[_ProjectInfo, ...]
    issues: tuple[_Issue, ...] = ()


@dataclass(frozen=True)
class _ProcRuntimeRetentionStub:
    runtime_root: Path
    apply: bool
    scanned: int
    selected: int
    removed: int
    skipped: int
    errors: int
    reclaimable_bytes: int
    reclaimed_bytes: int
    capped: bool

    def describe(self) -> str:
        suffix = " (removal budget reached)" if self.capped else ""
        verb = "removed" if self.apply else "would remove"
        return (
            f"{verb} {self.removed if self.apply else self.selected} proc runtime "
            f"dir(s) under {self.runtime_root}; scanned={self.scanned}, "
            f"reclaimable={self.reclaimable_bytes}, reclaimed={self.reclaimed_bytes}"
            f"{suffix}"
        )


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_collect_disk_footprint_attributes_owned_paths_and_strays(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    managed = tmp_path / "managed-tmp"
    sase_home = tmp_path / ".sase"
    projects = sase_home / "projects"
    workspace_root = tmp_path / "workspaces" / "proj"
    core = tmp_path / "sase-core"

    _write(managed / "cargo-targets" / "agent" / "build.o", "build")
    _write(sase_home / "procs" / "runtime" / "proc-1" / "state", "runtime")
    _write(sase_home / "cache" / "rust-prebuild" / "sets" / "a", "cache")
    _write(projects / "proj" / "artifacts" / "ace-run" / "202609" / "run", "run")
    _write(workspace_root / "sase_10" / "file", "workspace")
    _write(core / "Cargo.toml", "[workspace]\n")
    _write(core / "target" / "uv-tool-py" / "deps" / "lib", "deps")
    _write(
        core
        / "target"
        / "uv-tool-py"
        / "build"
        / "dev-update"
        / "incremental"
        / "session",
        "incremental",
    )

    stray = home / "forgotten-cargo-target"
    _write(stray / ".rustc_info.json", "{}")
    _write(stray / "debug" / "obj", "orphan")
    repo_target = home / "repo" / "target"
    _write(home / "repo" / ".git" / "HEAD", "ref: main\n")
    _write(repo_target / ".rustc_info.json", "{}")

    monkeypatch.setattr("sase.core.disk_footprint.managed_tmpdir_root", lambda: managed)
    monkeypatch.setattr("sase.core.disk_footprint.sase_home", lambda: sase_home)
    monkeypatch.setattr("sase.core.disk_footprint.sase_projects_dir", lambda: projects)
    monkeypatch.setattr(
        "sase.core.disk_footprint.procs_dir", lambda: sase_home / "procs"
    )
    monkeypatch.setattr("sase.core.disk_footprint._resolve_sase_core_dir", lambda: core)

    report = collect_disk_footprint(
        home=home,
        workspace_inventory_fn=lambda **_kwargs: _Inventory(
            projects=(
                _ProjectInfo(
                    project="SASE",
                    project_key="proj",
                    root_dir=str(workspace_root),
                    cleanup_ttl_days=14,
                ),
            )
        ),
    )

    rows_by_path = {Path(row.path): row for row in report.rows}
    assert rows_by_path[managed / "cargo-targets"].owner == "managed_tmp_reaper"
    assert rows_by_path[projects / "proj" / "artifacts" / "ace-run"].owner == (
        "artifact_run_retention"
    )
    assert rows_by_path[workspace_root].owner == "workspace_cleanup_and_compact"
    assert rows_by_path[stray].status == "unowned"
    assert repo_target not in rows_by_path
    assert all(row.owner and row.horizon for row in report.rows)


def test_collect_disk_footprint_uses_configured_managed_tmp_horizons(
    tmp_path: Path,
    monkeypatch,
) -> None:
    managed = tmp_path / "managed-tmp"
    sase_home = tmp_path / ".sase"
    _write(managed / "muse-prompts" / "prompt", "prompt")
    monkeypatch.setattr("sase.core.disk_footprint.managed_tmpdir_root", lambda: managed)
    monkeypatch.setattr("sase.core.disk_footprint.sase_home", lambda: sase_home)
    monkeypatch.setattr(
        "sase.core.disk_footprint.procs_dir", lambda: sase_home / "procs"
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint.sase_projects_dir",
        lambda: sase_home / "projects",
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_inventory.current_managed_tmp_horizons",
        lambda: {"muse-prompts": 7 * 24 * 3600},
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_inventory.get_managed_tmp_handoff_horizon_seconds",
        lambda: 3 * 24 * 3600,
    )
    monkeypatch.setattr("sase.core.disk_footprint._resolve_sase_core_dir", lambda: None)

    report = collect_disk_footprint(
        include_strays=False,
        tree_size_fn=lambda _path: 0,
        workspace_inventory_fn=lambda **_kwargs: _Inventory(projects=()),
    )

    row = next(row for row in report.rows if row.path == str(managed / "muse-prompts"))
    assert row.horizon == "7d"


def test_workspace_inventory_failures_remain_visible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    managed = tmp_path / "managed-tmp"
    sase_home = tmp_path / ".sase"
    monkeypatch.setattr("sase.core.disk_footprint.managed_tmpdir_root", lambda: managed)
    monkeypatch.setattr("sase.core.disk_footprint.sase_home", lambda: sase_home)
    monkeypatch.setattr(
        "sase.core.disk_footprint.procs_dir", lambda: sase_home / "procs"
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint.sase_projects_dir",
        lambda: sase_home / "projects",
    )
    monkeypatch.setattr("sase.core.disk_footprint._resolve_sase_core_dir", lambda: None)

    def fail_inventory(**_kwargs):
        raise RuntimeError("registry offline")

    report = collect_disk_footprint(
        include_strays=False,
        tree_size_fn=lambda _path: 0,
        workspace_inventory_fn=fail_inventory,
    )

    row = next(row for row in report.rows if row.name == "<workspace inventory>")
    assert row.coverage == "unresolved"
    assert report.coverage_status == "partial"
    assert report.unresolved_owner_coverage
    assert any(
        "registry offline" in diagnostic for diagnostic in report.scan_diagnostics
    )


def test_overlapping_workspace_and_primary_rows_count_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_root = tmp_path / "workspaces" / "proj"
    primary = workspace_root / "primary"
    monkeypatch.setattr(
        "sase.core.disk_footprint.managed_tmpdir_root", lambda: tmp_path / "managed"
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint.sase_home", lambda: tmp_path / ".sase"
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint.procs_dir", lambda: tmp_path / ".sase" / "procs"
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint.sase_projects_dir",
        lambda: tmp_path / ".sase" / "projects",
    )
    monkeypatch.setattr("sase.core.disk_footprint._resolve_sase_core_dir", lambda: None)

    def sizes(path: Path) -> int:
        if path == workspace_root:
            return 100
        if path == primary:
            return 40
        return 0

    report = collect_disk_footprint(
        include_strays=False,
        tree_size_fn=sizes,
        workspace_inventory_fn=lambda **_kwargs: _Inventory(
            projects=(
                _ProjectInfo(
                    project="SASE",
                    project_key="proj",
                    root_dir=str(workspace_root),
                    primary_workspace_dir=str(primary),
                    cleanup_ttl_days=14,
                    share_git_objects=True,
                ),
            )
        ),
    )

    rows_by_path = {Path(row.path): row for row in report.rows if row.path}
    assert rows_by_path[workspace_root].exclusive_size_bytes == 60
    assert rows_by_path[primary].exclusive_size_bytes == 40
    assert rows_by_path[primary].overlap_parent_path == str(workspace_root)
    assert report.logical_total_bytes == 140
    assert report.total_bytes == 100


def test_cargo_stray_scan_shares_a_bounded_listing_budget(tmp_path: Path) -> None:
    home = tmp_path / "home"
    for index in range(20):
        _write(home / f"wide-{index}" / "target" / ".rustc_info.json", "{}")

    _rows, visited, truncated = cargo_stray_rows(
        home,
        excludes=(),
        tree_size_fn=lambda _path: 0,
        budget=InventoryScanBudget(max_nodes=4, max_seconds=60.0),
    )

    assert truncated is True
    assert visited <= 2


def test_disk_reap_proc_preview_uses_runtime_owner(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.core.disk_footprint._managed_tmp_reap_step",
        lambda *, apply, **_kwargs: DiskReapStep(
            owner="managed_tmp_reaper",
            mode="dry_run" if not apply else "apply",
            summary="tmp",
        ),
    )

    def fake_sweep(**kwargs):
        assert kwargs["apply"] is False
        return _ProcRuntimeRetentionStub(
            runtime_root=Path("/tmp/runtime"),
            apply=False,
            scanned=12,
            selected=3,
            removed=0,
            skipped=9,
            errors=0,
            reclaimable_bytes=1234,
            reclaimed_bytes=0,
            capped=True,
        )

    monkeypatch.setattr(
        "sase.core.disk_footprint.sweep_orphan_proc_runtime_dirs",
        fake_sweep,
    )

    result = run_disk_reap(
        apply=False,
        include_artifact_runs=False,
        include_workspace_compact=False,
    )

    proc_step = next(
        step for step in result.steps if step.owner == "proc_runtime_sweep"
    )
    assert proc_step.reclaimed_bytes == 1234
    assert "would remove 3 proc runtime dir(s)" in proc_step.summary


def test_managed_tmp_reap_step_reports_age_only_bytes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    managed = tmp_path / "managed"
    stale = managed / "editors" / "note.md"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"x" * 512)
    ancient = 1_800_000_000.0 - 400 * 24 * 3600
    os.utime(stale, (ancient, ancient))
    monkeypatch.setattr(
        "sase.core.managed_tmp_reaper.managed_tmpdir_root", lambda: managed
    )

    step = managed_tmp_reap_step(
        apply=False,
        filesystem_available_bytes=64 * 1024**3,
    )

    assert stale.exists()
    assert step.reclaimed_bytes == 512
