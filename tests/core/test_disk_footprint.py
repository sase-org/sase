"""Tests for SASE disk-footprint inventory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.core.disk_footprint import collect_disk_footprint


@dataclass(frozen=True)
class _ProjectInfo:
    project: str
    project_key: str
    root_dir: str
    cleanup_ttl_days: int


@dataclass(frozen=True)
class _Inventory:
    projects: tuple[_ProjectInfo, ...]


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
        core / "target" / "uv-tool-py" / "dev-update" / "incremental" / "session",
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
