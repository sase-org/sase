"""Tests for SASE disk-footprint inventory collection."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase.core.disk_footprint import collect_disk_footprint
from sase.core.disk_footprint_inventory import cargo_stray_rows
from sase.core.disk_footprint_utils import InventoryScanBudget

from tests.core._disk_footprint_helpers import _Inventory, _ProjectInfo, _write


def _roomy_usage(total: int = 100 * 1024**3, used: int = 10 * 1024**3):
    """Fake ``shutil.disk_usage`` with complete attribution and no pressure."""

    return lambda _path: SimpleNamespace(total=total, used=used, free=total - used)


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
        disk_usage_fn=_roomy_usage(),
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
        disk_usage_fn=_roomy_usage(),
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
    (tmp_path / ".sase" / "projects").mkdir(parents=True)
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
        disk_usage_fn=_roomy_usage(),
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


def test_managed_tmp_rows_cover_every_registered_root(
    tmp_path: Path, monkeypatch
) -> None:
    """A stale service environment must not hide the writers' real root.

    When the registry knows a second root (the incident shape: agents
    write under ``SASE_TMPDIR`` while the service resolves elsewhere),
    inventory sizes buckets under both roots instead of only the
    effective one.
    """
    from sase.core.disk_footprint_inventory import managed_tmp_rows

    first = tmp_path / "first-tmp"
    second = tmp_path / "second-tmp"
    _write(first / "cargo-targets" / "agent-a" / "build.o", "build")
    _write(second / "agent-tmp" / "agent-b" / "scratch", "scratch")
    monkeypatch.setattr(
        "sase.core.disk_footprint_inventory.effective_managed_tmp_roots",
        lambda *, effective_root, sase_home: [first, second],
    )

    rows = managed_tmp_rows(tree_size_fn=lambda _path: 7)

    by_path = {Path(row.path): row for row in rows}
    assert by_path[first / "cargo-targets"].owner == "managed_tmp_reaper"
    assert by_path[second / "agent-tmp"].owner == "managed_tmp_reaper"
    assert by_path[first / "cargo-targets"].name == "first-tmp/cargo-targets"
    assert by_path[second / "agent-tmp"].name == "second-tmp/agent-tmp"


def test_workspace_rows_name_heavy_subtrees(tmp_path: Path, monkeypatch) -> None:
    """Workspace checkouts report their heavy sub-trees before the strays."""
    (tmp_path / ".sase" / "projects").mkdir(parents=True)
    workspace_root = tmp_path / "workspaces" / "proj"
    _write(workspace_root / ".git" / "objects" / "ab" / "cdef", "object")
    _write(workspace_root / ".pytest_cache" / "sase-visual" / "report", "v")
    _write(workspace_root / "sase" / "repos" / "linked", "r")
    _write(workspace_root / ".venv" / "lib" / "site", "v")
    _write(workspace_root / "target" / "debug" / "artifact", "t")
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

    report = collect_disk_footprint(
        include_strays=False,
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
        disk_usage_fn=_roomy_usage(),
    )

    rows_by_path = {Path(row.path): row for row in report.rows if row.path}
    for child in (".git/objects", ".pytest_cache", "sase/repos", ".venv", "target"):
        child_row = rows_by_path[workspace_root / child]
        assert child_row.section == "workspaces"
        assert child_row.owner == "workspace_cleanup_and_compact"
        assert child_row.overlap_parent_path == str(workspace_root)
    parent = rows_by_path[workspace_root]
    children_total = sum(
        rows_by_path[workspace_root / child].size_bytes
        for child in (".git/objects", ".pytest_cache", "sase/repos", ".venv", "target")
    )
    assert parent.exclusive_size_bytes == parent.size_bytes - children_total


def test_unattributed_row_reports_df_gap_when_coverage_partial(
    tmp_path: Path, monkeypatch
) -> None:
    """`df` used minus attributed bytes surfaces instead of a small owner."""
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

    def fail_inventory(**_kwargs):
        raise RuntimeError("registry offline")

    report = collect_disk_footprint(
        include_strays=False,
        tree_size_fn=lambda _path: 0,
        workspace_inventory_fn=fail_inventory,
        disk_usage_fn=lambda _path: SimpleNamespace(total=1000, used=800, free=200),
    )

    row = next(row for row in report.rows if row.owner == "unattributed")
    assert row.name == "unattributed"
    assert row.size_bytes == 800
    assert row.exclusive_size_bytes == 800
    assert row.path == ""
    assert "sase disk list" in (row.reclaim or "")


def test_budget_exhaustion_clips_stray_walk_but_keeps_workspace_rows(
    tmp_path: Path, monkeypatch
) -> None:
    """Known heavy locations are sized before the generic stray walk."""
    managed = tmp_path / "managed-tmp"
    for bucket in ("cargo-targets", "agent-tmp", "build-targets"):
        _write(managed / bucket / "entry" / "payload", "x")
    home = tmp_path / "home"
    _write(home / "forgotten" / "target" / ".rustc_info.json", "{}")
    workspace_root = tmp_path / "workspaces" / "proj"
    _write(workspace_root / "file", "workspace")
    monkeypatch.setattr("sase.core.disk_footprint.managed_tmpdir_root", lambda: managed)
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
    monkeypatch.setattr(
        "sase.core.disk_footprint_inventory_collect.STRAY_MAX_VISITED", 2
    )

    report = collect_disk_footprint(
        home=home,
        tree_size_fn=lambda path: 100 if path == workspace_root else 0,
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
        disk_usage_fn=lambda _path: SimpleNamespace(total=1000, used=900, free=100),
    )

    rows_by_path = {Path(row.path): row for row in report.rows if row.path}
    assert rows_by_path[workspace_root].size_bytes == 100
    assert report.stray_scan_truncated is True
    assert report.coverage_status == "partial"


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
    monkeypatch.setattr(
        "sase.core.disk_footprint_inventory.effective_managed_tmp_roots",
        lambda *, effective_root, sase_home: [effective_root],
    )

    rows = managed_tmp_rows(tree_size_fn=lambda _path: 5)

    by_name = {row.name: row for row in rows}
    assert by_name["cargo-targets"].owner == "managed_tmp_reaper"
    assert Path(by_name["cargo-targets"].path) == effective / "cargo-targets"
