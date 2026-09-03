"""Tests for managed AGENTS provider shim synchronization."""

from __future__ import annotations

from pathlib import Path

import pytest

import sase.config.core as config_core
from sase.amd.constants import PROVIDER_SHIM_FILES
from sase.main import init_memory_handler
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_handler,
    write,
)


def test_init_memory_overwrites_provider_shims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(project_root / "AGENTS.md", "@sase/memory/sase.md\n")
    write(project_root / "CLAUDE.md", "old instructions\n")

    assert run_handler() == 0

    # Every provider file is overwritten with a byte-for-byte copy of AGENTS.md.
    agents = (project_root / "AGENTS.md").read_text()
    for filename in PROVIDER_SHIM_FILES:
        assert (project_root / filename).read_text() == agents


def test_init_memory_chezmoi_custom_static_shim_blocks_template_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        use_chezmoi=True,
    )
    monkeypatch.setattr(init_memory_handler, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(config_core, "CHEZMOI_HOME", chezmoi_home)
    write(chezmoi_home / "dot_config" / "sase" / "sase.yml", "use_chezmoi: true\n")
    write(
        chezmoi_home / "dot_config" / "sase" / "sase_apollo.yml",
        "id:\n  username: bbugyi200\n  machine_name: apollo\n"
        'memory:\n  h1_title: "apollo title"\n',
    )
    write(
        chezmoi_home / ".chezmoiignore",
        '{{ if ne .chezmoi.hostname "apollo" }}\n'
        ".config/sase/sase_apollo.yml\n"
        "{{ end }}\n",
    )
    write(chezmoi_home / "CLAUDE.md", "my custom claude instructions\n")

    plan = plan_memory()
    assert any(
        "custom legacy provider instruction file" in blocker
        for blocker in plan.blockers
    )
    assert run_handler() == 1
    assert (chezmoi_home / "CLAUDE.md").read_text(encoding="utf-8") == (
        "my custom claude instructions\n"
    )
    assert not (chezmoi_home / "CLAUDE.md.tmpl").exists()
