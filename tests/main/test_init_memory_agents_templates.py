"""Tests for human-editable ``sase memory init`` agent templates."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

import sase.config.core as config_core
from sase.amd._agents_doc import _long_memory_entry_path, parse_amd_agents_document
from sase.main import init_memory_handler
from tests.main.init_memory_handler_helpers import (
    long_note,
    patch_standard_paths,
    plan_memory,
    run_handler,
    write,
)


def test_amd_parser_normalizes_legacy_memory_references() -> None:
    parsed = parse_amd_agents_document(
        "## Tier 1 (core) Memory\n\n"
        "- @memory/sase.md\n\n"
        "## Tier 2 (reference) Memory\n\n"
        "**`memory/detail.md`**  \nDetails.\n"
    )

    assert parsed.short_memory_paths == ("sase/memory/sase.md",)
    assert tuple(entry.path for entry in parsed.long_memory_entries) == (
        "sase/memory/detail.md",
    )


def test_amd_parser_accepts_legacy_memory_section_anchors() -> None:
    parsed = parse_amd_agents_document(
        "## Tier 1 (short"
        "-term) Memory\n\n"
        "### SASE (sase)\n\n"
        "## Tier 2 (long"
        "-term) Memory\n\n"
        "**`memory/detail.md`**  \nDetails.\n"
    )

    assert parsed.has_short_section
    assert parsed.has_long_section
    assert parsed.short_memory_paths == ("sase/memory/sase.md",)
    assert tuple(entry.path for entry in parsed.long_memory_entries) == (
        "sase/memory/detail.md",
    )


def test_amd_parser_preserves_block_long_memory_descriptions() -> None:
    parsed = parse_amd_agents_document(
        "## Tier 1 (core) Memory\n\n"
        "### 1. SASE (sase)\n\n"
        "## Tier 2 (reference) Memory\n\n"
        "**`sase/memory/block.md`**  \n"
        "Lead paragraph.\n"
        "\n"
        "- One\n"
        "- Two\n"
        "\n"
        "Trailer. _Read when touching block memory._\n"
        "\n"
        "**`sase/memory/next.md`**  \n"
        "Next description.\n"
        "\n"
        "## Other\n"
    )

    assert tuple(entry.path for entry in parsed.long_memory_entries) == (
        "sase/memory/block.md",
        "sase/memory/next.md",
    )
    assert parsed.long_memory_entries[0].description == (
        "Lead paragraph.\n\n- One\n- Two\n\nTrailer."
    )
    assert parsed.long_memory_entries[1].description == "Next description."


def test_amd_parser_reads_numbered_and_unnumbered_long_memory_sections() -> None:
    unnumbered = parse_amd_agents_document(
        "## Tier 1 (core) Memory\n\n"
        "### SASE (sase)\n\n"
        "## Tier 2 (reference) Memory\n\n"
        "### `sase/memory/block.md`\n\n"
        "Lead paragraph.\n\n"
        "- One\n"
        "- Two\n\n"
        "Trailer.\n\n"
        "### `sase/memory/next.md`\n\n"
        "Next description.\n"
    )
    numbered = parse_amd_agents_document(
        "## 2. Tier 2 (reference) Memory\n\n"
        "### 2.1 `sase/memory/block.md`\n\n"
        "Lead paragraph.\n\n"
        "- One\n"
        "- Two\n\n"
        "Trailer.\n\n"
        "### 2.2 `sase/memory/next.md`\n\n"
        "Next description.\n"
    )

    for parsed in (unnumbered, numbered):
        assert tuple(entry.path for entry in parsed.long_memory_entries) == (
            "sase/memory/block.md",
            "sase/memory/next.md",
        )
        assert parsed.long_memory_entries[0].description == (
            "Lead paragraph.\n\n- One\n- Two\n\nTrailer."
        )
        assert parsed.long_memory_entries[1].description == "Next description."


def test_amd_parser_reads_mixed_legacy_and_section_long_memory_entries() -> None:
    parsed = parse_amd_agents_document(
        "## Tier 2 (reference) Memory\n\n"
        "### `sase/memory/section.md`\n\n"
        "Section description.\n\n"
        "**`memory/legacy.md`**  \n"
        "Legacy description.\n"
    )

    assert tuple(entry.path for entry in parsed.long_memory_entries) == (
        "sase/memory/section.md",
        "sase/memory/legacy.md",
    )
    assert parsed.long_memory_entries[0].description == "Section description."
    assert parsed.long_memory_entries[1].description == "Legacy description."


def test_amd_parser_reads_legacy_h4_long_memory_sections() -> None:
    parsed = parse_amd_agents_document(
        "## 2. Tier 2 (reference) Memory\n\n"
        "### 2.1 Long-Term Memory Files\n\n"
        "The below files contain detailed reference material. When working in "
        "their domain, you MUST use your `/sase_memory_read` skill.\n\n"
        "#### 2.1.1 `sase/memory/block.md`\n\n"
        "Lead paragraph.\n\n"
        "#### 2.1.2 `sase/memory/next.md`\n\n"
        "Next description.\n"
    )

    assert tuple(entry.path for entry in parsed.long_memory_entries) == (
        "sase/memory/block.md",
        "sase/memory/next.md",
    )
    assert parsed.long_memory_entries[0].description == "Lead paragraph."
    assert parsed.long_memory_entries[1].description == "Next description."


def test_amd_parser_does_not_absorb_tier2_intro_into_description() -> None:
    parsed = parse_amd_agents_document(
        "## 2. Tier 2 (reference) Memory\n\n"
        "The below files contain detailed reference material. When working in "
        "their domain, you MUST use your `/sase_memory_read` skill to review "
        "their contents. Do not read canonical memory files directly.\n\n"
        "### 2.1 `sase/memory/block.md`\n\n"
        "Lead paragraph.\n\n"
        "### 2.2 `sase/memory/next.md`\n\n"
        "Next description.\n"
    )

    assert tuple(entry.path for entry in parsed.long_memory_entries) == (
        "sase/memory/block.md",
        "sase/memory/next.md",
    )
    assert parsed.long_memory_entries[0].description == "Lead paragraph."
    assert parsed.long_memory_entries[1].description == "Next description."
    assert all(
        "below files contain detailed reference material" not in entry.description
        for entry in parsed.long_memory_entries
    )


def test_long_memory_entry_path_accepts_section_and_legacy_shapes() -> None:
    assert (
        _long_memory_entry_path("### `sase/memory/cli_rules.md`")
        == "sase/memory/cli_rules.md"
    )
    assert (
        _long_memory_entry_path("### 2.1 `memory/cli_rules.md`")
        == "sase/memory/cli_rules.md"
    )
    assert (
        _long_memory_entry_path("#### 2.1.1 `sase/memory/cli_rules.md`")
        == "sase/memory/cli_rules.md"
    )
    assert (
        _long_memory_entry_path("**`memory/cli_rules.md`**  Details.")
        == "sase/memory/cli_rules.md"
    )
    assert _long_memory_entry_path("### Extra (extra)") is None


def _managed_template(marker: str) -> str:
    return f"""# {{{{ title }}}}

{marker}

## Tier 1 (core) Memory

{{{{ tier1_sections }}}}

## Tier 2 (reference) Memory

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
        'memory:\n  h1_title: "Project Instructions"\n'
        "amd_agents_template: templates/project-agents.md\n",
    )
    write(
        project_root / "templates" / "project-agents.md",
        _managed_template("Project template frame."),
    )
    write(
        project_root / "sase" / "memory" / "detail.md",
        long_note("# Detail\n", description="Detailed reference."),
    )

    assert run_handler() == 0

    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Project Instructions\n\nProject template frame.\n")
    parsed = parse_amd_agents_document(agents)
    assert parsed.has_short_section
    assert parsed.has_long_section
    assert parsed.short_memory_paths == (
        "sase/memory/sase.md",
        "sase/memory/task_types.md",
    )
    assert tuple(entry.path for entry in parsed.long_memory_entries) == (
        "sase/memory/detail.md",
        "sase/memory/sase_artifacts.md",
        "sase/memory/sase_beads.md",
    )
    assert plan_memory().actions == ()

    write(
        project_root / "templates" / "project-agents.md",
        _managed_template("Updated project template frame."),
    )
    assert ("overwrite", project_root / "AGENTS.md") in {
        (action.operation, action.path) for action in plan_memory().actions
    }


def test_nested_memory_agents_template_override_renders_and_round_trips(
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
        "memory:\n"
        '  h1_title: "Project Instructions"\n'
        "  agents_template: templates/project-agents.md\n",
    )
    write(
        project_root / "templates" / "project-agents.md",
        _managed_template("Nested project template frame."),
    )

    assert run_handler() == 0

    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith(
        "# Project Instructions\n\nNested project template frame.\n"
    )


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
    write(config_dir / "sase.yml", 'memory:\n  h1_title: "Home Instructions"\n')
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
    write(source_config_dir / "sase.yml", 'memory:\n  h1_title: "Source Home"\n')
    write(
        source_config_dir / "AGENTS.template.md",
        _managed_template("Chezmoi source template frame."),
    )

    deployed: list[Path] = []

    def fake_deploy(paths: Iterable[Path], **_kwargs: object) -> int:
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
    assert not (home_root / "sase" / "memory" / "sase.md").exists()


@pytest.mark.parametrize(
    ("template", "expected_error"),
    [
        (
            "# {{ title }}\n\n"
            "## Tier 1 (core) Memory\n\n{{ tier1_sections }}\n\n"
            "## Tier 2 (reference) Memory\n",
            "template must contain {{ tier2_entries }}",
        ),
        ("{% if %}\n", "template error"),
        (
            _managed_template("{{ unknown_value }}"),
            "unknown template placeholder {{ unknown_value }}",
        ),
        (
            _managed_template("frame").replace(
                "## Tier 1 (core) Memory",
                "## Short Memory",
            ),
            "missing structural anchor `## Tier 1 (core) Memory`",
        ),
        (
            _managed_template("frame").replace(
                "## Tier 2 (reference) Memory",
                "## Long Memory",
            ),
            "missing structural anchor `## Tier 2 (reference) Memory`",
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
        'memory:\n  h1_title: "Project Instructions"\n'
        "amd_agents_template: templates/project-agents.md\n",
    )
    write(project_root / "templates" / "project-agents.md", template)

    plan = plan_memory()

    assert any(expected_error in blocker for blocker in plan.blockers)
    assert run_handler() == 1
    assert not (project_root / "AGENTS.md").exists()
    assert not (project_root / "sase" / "memory" / "sase.md").exists()
