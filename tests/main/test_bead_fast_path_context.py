"""Tests for lightweight bead CLI context resolution."""

from __future__ import annotations

from pathlib import Path

from sase.main.bead_fast_path import (
    _BEADS_DIRNAME,
    _BEADS_DIRNAME_NON_VC,
    _resolve_fast_path_context,
    _resolve_lightweight_beads_context,
)


def _set_sdd_policy(monkeypatch, storage: str) -> None:
    vcs_name = {
        "in_tree": "bare_git",
        "separate_repo": "github",
    }.get(storage)
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda _cwd: vcs_name)
    monkeypatch.setattr(
        "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
        lambda _name: storage if storage != "local" else None,
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
    _set_sdd_policy(monkeypatch, "in_tree")

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
    _set_sdd_policy(monkeypatch, "in_tree")

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
    _set_sdd_policy(monkeypatch, "in_tree")

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
    _set_sdd_policy(monkeypatch, "local")

    result = _resolve_lightweight_beads_context(sibling.resolve())

    assert result is not None
    read_dirs, write_dir, beads_dirname = result
    assert read_dirs == [primary / ".sase" / "sdd" / "beads"]
    assert write_dir == primary / ".sase" / "sdd" / "beads"
    assert beads_dirname == _BEADS_DIRNAME_NON_VC


def test_lightweight_context_uses_workspace_local_store_in_separate_repo_mode(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    sibling = tmp_path / "workspaces" / "sase_106"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (sibling / ".sase" / "sdd" / "beads").mkdir(parents=True)
    nested = sibling / "src" / "pkg"
    nested.mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    _set_sdd_policy(monkeypatch, "separate_repo")

    result = _resolve_lightweight_beads_context(nested.resolve())

    assert result is not None
    read_dirs, write_dir, beads_dirname = result
    assert read_dirs == [sibling / ".sase" / "sdd" / "beads"]
    assert write_dir == sibling / ".sase" / "sdd" / "beads"
    assert beads_dirname == _BEADS_DIRNAME_NON_VC


def test_lightweight_context_treats_bare_git_as_in_tree(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    sibling = tmp_path / "workspaces" / "sase_106"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (sibling / "sdd/beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda cwd: "bare_git")
    monkeypatch.setattr(
        "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
        lambda vcs_name: "in_tree" if vcs_name == "bare_git" else None,
    )

    result = _resolve_lightweight_beads_context(sibling.resolve())

    assert result is not None
    read_dirs, write_dir, beads_dirname = result
    assert read_dirs == [sibling / "sdd/beads"]
    assert write_dir == sibling / "sdd/beads"
    assert beads_dirname == _BEADS_DIRNAME


def test_fast_path_ignores_legacy_store_by_default(tmp_path: Path, monkeypatch) -> None:
    primary = tmp_path / "workspaces" / "sase"
    (primary / ".sase_beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    _set_sdd_policy(monkeypatch, "local")
    monkeypatch.chdir(primary)

    context = _resolve_fast_path_context(["update", "sase-1", "--status", "closed"])

    assert context is None


def test_fast_path_routes_write_commands_for_non_vc_store(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    _set_sdd_policy(monkeypatch, "local")
    monkeypatch.chdir(primary)

    context = _resolve_fast_path_context(["update", "sase-1", "--status", "closed"])

    assert context is not None
    assert context.write_beads_dir == primary / ".sase" / "sdd" / "beads"
    assert _resolve_fast_path_context(["create", "--title", "Created"]) is not None


def _write_project_file(home: Path, project_name: str, primary: Path) -> None:
    project_dir = home / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(
        f"WORKSPACE_DIR: {primary}\n",
        encoding="utf-8",
    )
