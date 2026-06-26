"""Tests for ``sase memory init`` agent-document behavior.

These cover the agent-document initialization that ``sase memory init`` now
owns: managed ``AGENTS.md`` sync for home/chezmoi roots, and the dropped legacy
single-custom-provider-file migration (provider shims are still repaired, but
custom provider content is no longer copied into ``AGENTS.md``).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

import sase.config.core as config_core
from sase.amd.constants import (
    CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT,
    PROVIDER_SHIM_CONTENT,
    PROVIDER_SHIM_FILES,
)
from sase.main import init_memory_handler
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    run_handler,
    write,
)

_MINIMAL_AGENTS = "# Agent Instructions\n\n@memory/sase.md\n"


def short_note(body: str) -> str:
    return "---\ntype: short\nparent: AGENTS.md\n---\n" + body


def home_provider_shim_content(root: Path) -> str:
    return f"@{root.resolve(strict=False).as_posix()}/AGENTS.md\n"


def test_init_memory_manages_live_home_from_user_overlay(
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
    # The home AMD title is read from the live user config dir.
    monkeypatch.setattr(config_core, "CONFIG_DIR", config_dir)
    write(config_dir / "sase.yml", 'amd_h1_title: "Athena Home"\n')

    assert run_handler() == 0

    agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Athena Home\n")
    assert "## Tier 1 (short-term) Memory" in agents
    assert "- @memory/sase.md" in agents
    for filename in PROVIDER_SHIM_FILES:
        assert (home_root / filename).read_text(encoding="utf-8") == (
            home_provider_shim_content(home_root)
        )


def test_init_memory_manages_chezmoi_home_from_source_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    project_root.mkdir()
    home_root.mkdir()
    chezmoi_home.mkdir(parents=True)
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        use_chezmoi=True,
    )
    monkeypatch.setattr(init_memory_handler, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(config_core, "CHEZMOI_HOME", chezmoi_home)
    write(
        chezmoi_home / "dot_config" / "sase" / "sase.yml",
        'amd_h1_title: "Source Title"\n',
    )

    deployed: list[Path] = []

    def fake_deploy(paths: Iterable[Path]) -> int:
        deployed.extend(paths)
        return 0

    monkeypatch.setattr(init_memory_handler, "_deploy_to_chezmoi", fake_deploy)

    assert run_handler() == 0

    agents = (chezmoi_home / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Source Title\n")
    assert "- @memory/sase.md" in agents
    for filename in PROVIDER_SHIM_FILES:
        assert (chezmoi_home / f"{filename}.tmpl").read_text(encoding="utf-8") == (
            CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT
        )
        assert not (chezmoi_home / filename).exists()
    assert chezmoi_home / "AGENTS.md" in deployed


def test_init_memory_does_not_migrate_single_custom_provider_file(
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
    write(project_root / "CLAUDE.md", "# Legacy Custom Instructions\n\nKeep this.\n")

    assert run_handler() == 0

    # The legacy migration is gone: a minimal AGENTS.md is created and the
    # custom provider file is overwritten with a shim instead of being copied
    # into AGENTS.md.
    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents == _MINIMAL_AGENTS
    assert "Keep this." not in agents
    assert (project_root / "CLAUDE.md").read_text(encoding="utf-8") == (
        PROVIDER_SHIM_CONTENT
    )


def test_init_memory_overwrites_multiple_custom_provider_files(
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
    write(project_root / "CLAUDE.md", "# Claude custom\n")
    write(project_root / "GEMINI.md", "# Gemini custom\n")

    # The old AMD migration blocked on multiple custom provider files; memory
    # init now simply repairs each preferred-path shim and creates the minimal
    # AGENTS.md.
    assert run_handler() == 0

    assert (project_root / "AGENTS.md").read_text(encoding="utf-8") == _MINIMAL_AGENTS
    assert (project_root / "CLAUDE.md").read_text(encoding="utf-8") == (
        PROVIDER_SHIM_CONTENT
    )
    assert (project_root / "GEMINI.md").read_text(encoding="utf-8") == (
        PROVIDER_SHIM_CONTENT
    )
