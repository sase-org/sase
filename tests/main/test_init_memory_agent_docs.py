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
from sase.amd.constants import PROVIDER_SHIM_FILES
from sase.main import init_memory_handler
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    run_handler,
    write,
)


def _assert_derived_managed_agents(agents: str) -> None:
    """Assert *agents* is managed using the derived project title."""
    assert agents.startswith("# project - Agent Instructions\n\n")
    # The body is hard-wrapped at the repo Markdown width, so compare on
    # collapsed whitespace rather than pinning where the line breaks land.
    expected = (
        "# project - Agent Instructions "
        "IMPORTANT: You should not modify any of these memory files without "
        "approval from the user. However, when the user explicitly asks you to "
        "update a SASE memory file, that request already carries the required "
        "approval for the full workflow: make the requested edit to the "
        "canonical note under `sase/memory/`, then you MUST run "
        "`sase memory init` to regenerate `AGENTS.md`, the provider instruction "
        "shims, and the memory README. Do NOT ask for separate permission to "
        "initialize sase memory in that case. "
        "## 1. Tier 1 (short-term) Memory "
        "The following memories contain core (always loaded) context: "
        "### 1.1 SASE = Structured Agentic Software Engineering (sase)"
    )
    assert " ".join(agents.split()).startswith(expected)
    assert "@sase/memory/sase.md" not in agents
    assert "@AGENTS.md" not in agents
    assert agents.endswith("\n")


def short_note(body: str) -> str:
    return "---\ntype: short\nparent: AGENTS.md\n---\n" + body


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
    write(config_dir / "sase.yml", 'memory:\n  h1_title: "Athena Home"\n')

    assert run_handler() == 0

    agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Athena Home\n")
    assert "## 1. Tier 1 (short-term) Memory" in agents
    assert "### 1.1 SASE = Structured Agentic Software Engineering (sase)" in agents
    assert "- @sase/memory/sase.md" not in agents
    # Provider files are byte-for-byte copies of ``AGENTS.md``.
    for filename in PROVIDER_SHIM_FILES:
        assert (home_root / filename).read_text(encoding="utf-8") == agents


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
        'memory:\n  h1_title: "Source Title"\n',
    )

    deployed: list[Path] = []

    def fake_deploy(paths: Iterable[Path]) -> int:
        deployed.extend(paths)
        return 0

    monkeypatch.setattr(init_memory_handler, "_deploy_to_chezmoi", fake_deploy)

    assert run_handler() == 0

    agents = (chezmoi_home / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Source Title\n")
    assert "### 1.1 SASE = Structured Agentic Software Engineering (sase)" in agents
    assert "- @sase/memory/sase.md" not in agents
    # Chezmoi writes a static copy of ``AGENTS.md`` (no ``.tmpl``) because the
    # inlined content carries no template variables.
    for filename in PROVIDER_SHIM_FILES:
        assert (chezmoi_home / filename).read_text(encoding="utf-8") == agents
        assert not (chezmoi_home / f"{filename}.tmpl").exists()
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

    # The legacy migration is gone: managed AGENTS.md is created and the
    # custom provider file is overwritten with a shim instead of being copied
    # into AGENTS.md.
    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    _assert_derived_managed_agents(agents)
    assert "Keep this." not in agents
    assert (project_root / "CLAUDE.md").read_text(encoding="utf-8") == agents


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
    # init now simply repairs each preferred-path shim and creates managed
    # AGENTS.md.
    assert run_handler() == 0

    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    _assert_derived_managed_agents(agents)
    assert (project_root / "CLAUDE.md").read_text(encoding="utf-8") == agents
    assert (project_root / "GEMINI.md").read_text(encoding="utf-8") == agents
