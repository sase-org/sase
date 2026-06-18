"""Tests for the lightweight bead CLI context resolver."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.main import bead_fast_path
from sase.main.bead_fast_path import (
    _BEADS_DIRNAME,
    _BEADS_DIRNAME_NON_VC,
    _resolve_fast_path_context,
    _resolve_lightweight_beads_context,
    try_handle_bead_fast_path,
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


def test_lightweight_context_treats_bare_git_as_vc_when_config_false(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    sibling = tmp_path / "workspaces" / "sase_106"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (sibling / "sdd/beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sase.sdd.beads.get_sdd_config", lambda: False)
    monkeypatch.setattr("sase.sdd.beads.detect_vcs", lambda cwd: "bare_git")

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


def test_fast_path_routes_search_through_rust_executor(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    read_dir = tmp_path / "sdd/beads"
    read_dir.mkdir(parents=True)
    context = bead_fast_path._FastPathContext(
        read_beads_dirs=[read_dir],
        write_beads_dir=read_dir,
        relativize_design_paths=True,
    )
    calls: list[dict[str, Any]] = []

    def fake_binding(
        argv: list[str],
        read_beads_dirs: list[str],
        write_beads_dir: str,
        cwd: str,
        relativize_design_paths: bool,
    ) -> dict[str, object]:
        calls.append(
            {
                "argv": argv,
                "read_beads_dirs": read_beads_dirs,
                "write_beads_dir": write_beads_dir,
                "cwd": cwd,
                "relativize_design_paths": relativize_design_paths,
            }
        )
        return {"handled": True, "stdout": "rust search\n", "exit_code": 0}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        bead_fast_path,
        "_resolve_fast_path_context",
        lambda argv: context,
    )
    monkeypatch.setattr(
        "sase.core.rust.require_rust_binding",
        lambda name: fake_binding,
    )

    assert try_handle_bead_fast_path(["search", "needle"]) == 0

    assert capsys.readouterr().out == "rust search\n"
    assert calls == [
        {
            "argv": ["search", "needle"],
            "read_beads_dirs": [str(read_dir)],
            "write_beads_dir": str(read_dir),
            "cwd": str(tmp_path),
            "relativize_design_paths": True,
        }
    ]


def test_fast_path_defers_search_help_to_argparse(monkeypatch) -> None:
    def fail_context(argv: list[str]):
        raise AssertionError(f"context should not resolve for help: {argv}")

    monkeypatch.setattr(bead_fast_path, "_resolve_fast_path_context", fail_context)

    assert try_handle_bead_fast_path(["search", "--help"]) is None


def _write_project_file(home: Path, project_name: str, primary: Path) -> None:
    project_dir = home / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(
        f"WORKSPACE_DIR: {primary}\n",
        encoding="utf-8",
    )
