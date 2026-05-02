"""Tests for the lightweight bead CLI context resolver."""

from __future__ import annotations

from pathlib import Path

from sase.main.bead_fast_path import (
    _BEADS_DIRNAME,
    _resolve_fast_path_context,
    _resolve_lightweight_beads_context,
)


def test_lightweight_context_reads_current_and_legacy_workspace_stores(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    sibling = tmp_path / "workspaces" / "sase_106"
    (primary / "sdd/beads").mkdir(parents=True)
    (sibling / ".sase_beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = _resolve_lightweight_beads_context(sibling.resolve())

    assert result is not None
    read_dirs, write_dir, beads_dirname = result
    assert read_dirs == [primary / "sdd/beads", sibling / ".sase_beads"]
    assert write_dir == primary / "sdd/beads"
    assert beads_dirname == _BEADS_DIRNAME


def test_fast_path_allows_existing_legacy_store_as_write_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    (primary / ".sase_beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(primary)

    context = _resolve_fast_path_context(["update", "sase-1", "--status", "closed"])

    assert context is not None
    assert context.read_beads_dirs == [primary / ".sase_beads"]
    assert context.write_beads_dir == primary / ".sase_beads"
    assert context.relativize_design_paths is False


def test_fast_path_keeps_write_commands_disabled_for_non_vc_store(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(primary)

    context = _resolve_fast_path_context(["update", "sase-1", "--status", "closed"])

    assert context is None


def _write_project_file(home: Path, project_name: str, primary: Path) -> None:
    project_dir = home / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    (project_dir / f"{project_name}.gp").write_text(
        f"WORKSPACE_DIR: {primary}\n",
        encoding="utf-8",
    )
