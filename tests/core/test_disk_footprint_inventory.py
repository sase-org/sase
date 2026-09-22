"""Tests for SASE disk-footprint inventory collection."""

from __future__ import annotations

from pathlib import Path

from sase.core.disk_footprint import collect_disk_footprint
from sase.core.disk_footprint_inventory import cargo_stray_rows
from sase.core.disk_footprint_utils import InventoryScanBudget

from tests.core._disk_footprint_helpers import _Inventory, _ProjectInfo, _write


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
    assert rows_by_path[sase_home / "tools"].owner == "tool_run_retention"
    assert rows_by_path[sase_home / "tools"].horizon.startswith("summary 180d")
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


def test_managed_tmp_rows_counts_cargo_targets_under_effective_root(
    tmp_path: Path, monkeypatch
) -> None:
    """Disk-pressure attribution must see cargo-targets where agents write it.

    The inventory resolves its root through ``managed_tmpdir_root`` — the same
    ``$SASE_TMPDIR``-honoring resolution the launcher uses — so per-run cargo
    targets are owned by the reaper instead of surfacing as stray or top-owner
    noise (sase-15q).
    """
    from sase.core.disk_footprint_inventory import managed_tmp_rows

    effective = tmp_path / "effective-tmp"
    _write(effective / "cargo-targets" / "agent-ws0" / "build.o", "build")
    monkeypatch.setattr(
        "sase.core.disk_footprint_inventory.managed_tmpdir_root",
        lambda: effective,
    )

    rows = managed_tmp_rows(tree_size_fn=lambda _path: 5)

    by_name = {row.name: row for row in rows}
    assert by_name["cargo-targets"].owner == "managed_tmp_reaper"
    assert Path(by_name["cargo-targets"].path) == effective / "cargo-targets"
