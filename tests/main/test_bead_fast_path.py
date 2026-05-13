"""Tests for the lightweight bead CLI context resolver."""

from __future__ import annotations

from pathlib import Path

from sase.main.bead_fast_path import (
    _BEADS_DIRNAME,
    _BEADS_DIRNAME_NON_VC,
    _resolve_fast_path_context,
    _resolve_lightweight_beads_context,
)


def test_lightweight_context_reads_current_checkout_store(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    sibling = tmp_path / "workspaces" / "sase_106"
    (primary / "sdd/beads").mkdir(parents=True)
    (sibling / "sdd/beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sase.sdd.beads.get_sdd_config", lambda: True)

    result = _resolve_lightweight_beads_context(sibling.resolve())

    assert result is not None
    read_dirs, write_dir, beads_dirname = result
    assert read_dirs == [sibling / "sdd/beads"]
    assert write_dir == sibling / "sdd/beads"
    assert beads_dirname == _BEADS_DIRNAME


def test_lightweight_context_prefers_current_vc_store_over_primary_non_vc(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    sibling = tmp_path / "workspaces" / "sase_106"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (sibling / "sdd/beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sase.sdd.beads.get_sdd_config", lambda: True)

    result = _resolve_lightweight_beads_context(sibling.resolve())

    assert result is not None
    read_dirs, write_dir, beads_dirname = result
    assert read_dirs == [sibling / "sdd/beads"]
    assert write_dir == sibling / "sdd/beads"
    assert beads_dirname == _BEADS_DIRNAME


def test_lightweight_context_uses_primary_vc_store_over_primary_non_vc_in_vc_mode(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    sibling = tmp_path / "workspaces" / "sase_106"
    sibling.mkdir(parents=True)
    (primary / "sdd/beads").mkdir(parents=True)
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sase.sdd.beads.get_sdd_config", lambda: True)

    result = _resolve_lightweight_beads_context(sibling.resolve())

    assert result is not None
    read_dirs, write_dir, beads_dirname = result
    assert read_dirs == [primary / "sdd/beads"]
    assert write_dir == primary / "sdd/beads"
    assert beads_dirname == _BEADS_DIRNAME


def test_lightweight_context_uses_primary_non_vc_store_over_current_vc_in_non_vc_mode(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    sibling = tmp_path / "workspaces" / "sase_106"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (sibling / "sdd/beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sase.sdd.beads.get_sdd_config", lambda: False)

    result = _resolve_lightweight_beads_context(sibling.resolve())

    assert result is not None
    read_dirs, write_dir, beads_dirname = result
    assert read_dirs == [primary / ".sase" / "sdd" / "beads"]
    assert write_dir == primary / ".sase" / "sdd" / "beads"
    assert beads_dirname == _BEADS_DIRNAME_NON_VC


def test_fast_path_ignores_legacy_store_by_default(tmp_path: Path, monkeypatch) -> None:
    primary = tmp_path / "workspaces" / "sase"
    (primary / ".sase_beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sase.sdd.beads.get_sdd_config", lambda: False)
    monkeypatch.chdir(primary)

    context = _resolve_fast_path_context(["update", "sase-1", "--status", "closed"])

    assert context is None


def test_fast_path_keeps_write_commands_disabled_for_non_vc_store(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sase.sdd.beads.get_sdd_config", lambda: False)
    monkeypatch.chdir(primary)

    context = _resolve_fast_path_context(["update", "sase-1", "--status", "closed"])

    assert context is None


def _write_project_file(home: Path, project_name: str, primary: Path) -> None:
    project_dir = home / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(
        f"WORKSPACE_DIR: {primary}\n",
        encoding="utf-8",
    )
