"""Tests for human-editable ``sase memory init`` agent templates."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

import sase.config.core as config_core
from sase.amd._agents_doc import parse_amd_agents_document
from sase.main import init_memory_handler
from tests.main.init_memory_handler_helpers import (
    long_note,
    patch_standard_paths,
    plan_memory,
    run_handler,
    write,
)


def _managed_template(marker: str) -> str:
    return f"""# {{{{ title }}}}

{marker}

## Tier 1 (short-term) Memory

{{{{ tier1_sections }}}}

## Tier 2 (long-term) Memory

{{{{ tier2_entries }}}}
"""


def test_project_template_override_renders_and_round_trips(
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
    write(
        project_root / "sase.yml",
        "is_sase_managed: true\n"
        'amd_h1_title: "Project Instructions"\n'
        "amd_agents_template: templates/project-agents.md\n",
    )
    write(
        project_root / "templates" / "project-agents.md",
        _managed_template("Project template frame."),
    )
    write(
        project_root / "memory" / "detail.md",
        long_note("# Detail\n", description="Detailed reference."),
    )

    assert run_handler() == 0

    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Project Instructions\n\nProject template frame.\n")
    parsed = parse_amd_agents_document(agents)
    assert parsed.has_short_section
    assert parsed.has_long_section
    assert parsed.short_memory_paths == ("memory/sase.md",)
    assert tuple(entry.path for entry in parsed.long_memory_entries) == (
        "memory/detail.md",
    )
    assert plan_memory().actions == ()

    write(
        project_root / "templates" / "project-agents.md",
        _managed_template("Updated project template frame."),
    )
    assert ("overwrite", project_root / "AGENTS.md") in {
        (action.operation, action.path) for action in plan_memory().actions
    }


def test_root_config_template_beats_user_template(
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
    monkeypatch.setattr(config_core, "CONFIG_DIR", config_dir)
    write(config_dir / "sase.yml", 'amd_h1_title: "Home Instructions"\n')
    write(
        config_dir / "AGENTS.template.md",
        _managed_template("User template frame."),
    )
    write(
        home_root / "sase.yml",
        "amd_agents_template: templates/root-agents.md\n",
    )
    write(
        home_root / "templates" / "root-agents.md",
        _managed_template("Root template frame."),
    )

    assert run_handler() == 0

    agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Root template frame." in agents
    assert "User template frame." not in agents


def test_user_template_is_resolved_from_chezmoi_source_config_dir(
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
    source_config_dir = chezmoi_home / "dot_config" / "sase"
    write(source_config_dir / "sase.yml", 'amd_h1_title: "Source Home"\n')
    write(
        source_config_dir / "AGENTS.template.md",
        _managed_template("Chezmoi source template frame."),
    )

    deployed: list[Path] = []

    def fake_deploy(paths: Iterable[Path]) -> int:
        deployed.extend(paths)
        return 0

    monkeypatch.setattr(init_memory_handler, "_deploy_to_chezmoi", fake_deploy)

    assert run_handler() == 0

    agents = (chezmoi_home / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Source Home\n\nChezmoi source template frame.\n")
    assert chezmoi_home / "AGENTS.md" in deployed


def test_user_minimal_template_customizes_create_if_missing_fallback(
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
    monkeypatch.setattr(config_core, "CONFIG_DIR", config_dir)
    write(
        config_dir / "AGENTS.minimal.template.md",
        "# {{ title }}\n\nMinimal custom frame.\n\n{{ tier1_sections }}\n",
    )

    assert run_handler() == 0

    agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Agent Instructions\n\nMinimal custom frame.\n")
    assert "### 1. SASE = Structured Agentic Software Engineering (sase)" in agents


def test_invalid_minimal_template_blocks_without_writing(
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
    monkeypatch.setattr(config_core, "CONFIG_DIR", config_dir)
    write(config_dir / "AGENTS.minimal.template.md", "# {{ title }}\n")

    plan = plan_memory()

    assert any(
        "AGENTS.minimal.template.md: template must contain {{ tier1_sections }}"
        in blocker
        for blocker in plan.blockers
    )
    assert run_handler() == 1
    assert not (home_root / "AGENTS.md").exists()
    assert not (home_root / "memory" / "sase.md").exists()


@pytest.mark.parametrize(
    ("template", "expected_error"),
    [
        (
            "# {{ title }}\n\n"
            "## Tier 1 (short-term) Memory\n\n{{ tier1_sections }}\n\n"
            "## Tier 2 (long-term) Memory\n",
            "template must contain {{ tier2_entries }}",
        ),
        ("{% if %}\n", "template error"),
        (
            _managed_template("{{ unknown_value }}"),
            "unknown template placeholder {{ unknown_value }}",
        ),
        (
            _managed_template("frame").replace(
                "## Tier 1 (short-term) Memory",
                "## Short Memory",
            ),
            "missing structural anchor `## Tier 1 (short-term) Memory`",
        ),
        (
            _managed_template("frame").replace(
                "## Tier 2 (long-term) Memory",
                "## Long Memory",
            ),
            "missing structural anchor `## Tier 2 (long-term) Memory`",
        ),
        (
            _managed_template("frame").replace(
                "{{ tier1_sections }}",
                "{{ tier1_sections if false else '' }}",
            ),
            "unexpected Tier 1 memory paths",
        ),
    ],
)
def test_invalid_managed_template_blocks_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    template: str,
    expected_error: str,
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
    write(
        project_root / "sase.yml",
        "is_sase_managed: true\n"
        'amd_h1_title: "Project Instructions"\n'
        "amd_agents_template: templates/project-agents.md\n",
    )
    write(project_root / "templates" / "project-agents.md", template)

    plan = plan_memory()

    assert any(expected_error in blocker for blocker in plan.blockers)
    assert run_handler() == 1
    assert not (project_root / "AGENTS.md").exists()
    assert not (project_root / "memory" / "sase.md").exists()
