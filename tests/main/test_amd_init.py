"""Tests for ``sase amd init`` planning and application."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import sase.amd.init as amd_init
from sase.amd.constants import (
    CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT,
    HOME_PROVIDER_SHIM_CONTENT,
    PROVIDER_SHIM_CONTENT,
    PROVIDER_SHIM_FILES,
)
from sase.amd.init import _build_amd_init_plan, run_amd_init
from sase.amd.init import plan_amd_init


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def short_note(body: str) -> str:
    return "---\ntype: short\nparent: AGENTS.md\n---\n" + body


def long_note(
    body: str,
    *,
    description: str | None = "Long description.",
    extra_frontmatter: str = "",
) -> str:
    lines = ["---", "type: long", "parent: AGENTS.md"]
    if description is not None:
        lines.append(f"description: {description}")
    if extra_frontmatter:
        lines.extend(extra_frontmatter.strip().splitlines())
    lines.extend(["---", body])
    return "\n".join(lines)


def run_amd(*, check: bool = False, no_commit: bool = True) -> int:
    return run_amd_init(argparse.Namespace(check=check, no_commit=no_commit))


def run_bare_init_amd() -> int:
    return run_amd_init(
        argparse.Namespace(
            check=False,
            command="init",
            init_subcommand="amd",
            onboarding=True,
            no_commit=True,
        )
    )


def write_provider_shims(root: Path, content: str = PROVIDER_SHIM_CONTENT) -> None:
    for filename in PROVIDER_SHIM_FILES:
        write(root / filename, content)


def write_provider_shim_templates(
    root: Path,
    content: str = CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT,
) -> None:
    for filename in PROVIDER_SHIM_FILES:
        write(root / f"{filename}.tmpl", content)


def home_provider_shim_content(root: Path) -> str:
    return f"@{root.resolve(strict=False).as_posix()}/AGENTS.md\n"


def plan_amd() -> set[tuple[str, Path]]:
    plan = _build_amd_init_plan().plan
    return {(action.operation, action.path) for action in plan.actions}


def plan_bare_init_amd() -> set[tuple[str, Path]]:
    plan = plan_amd_init(argparse.Namespace(command="init", init_subcommand=None))
    return {(action.operation, action.path) for action in plan.actions}


def test_amd_init_creates_and_repairs_provider_shims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "AGENTS.md", "# Agent Instructions\n")
    write(tmp_path / "CLAUDE.md", "legacy provider instructions\n")

    assert run_amd() == 0

    for filename in PROVIDER_SHIM_FILES:
        assert (tmp_path / filename).read_text(encoding="utf-8") == (
            PROVIDER_SHIM_CONTENT
        )
    assert plan_amd() == set()


def test_amd_check_reports_drift_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "AGENTS.md", "# Agent Instructions\n")

    assert run_amd(check=True) == 1

    assert not (tmp_path / "CLAUDE.md").exists()
    out = capsys.readouterr().out
    assert "SASE initialization check" in out
    assert "init amd" in out
    assert "Needs attention:" in out


def test_bare_init_amd_plan_is_conservative_without_project_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert plan_bare_init_amd() == set()

    assert run_amd() == 0
    for filename in PROVIDER_SHIM_FILES:
        assert (tmp_path / filename).read_text(encoding="utf-8") == (
            PROVIDER_SHIM_CONTENT
        )


def test_bare_init_amd_plan_generates_when_project_title_is_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "sase.yml", 'amd_h1_title: "Managed Instructions"\n')
    write(tmp_path / "memory" / "short" / "sase.md", "# SASE\n")

    planned = plan_bare_init_amd()

    assert ("create", tmp_path / "AGENTS.md") in planned
    for filename in PROVIDER_SHIM_FILES:
        assert ("create", tmp_path / filename) in planned


def test_bare_init_amd_plan_uses_fallback_title_when_memory_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "memory" / "sase.md", short_note("# SASE\n"))
    write(
        tmp_path / "memory" / "cli_rules.md",
        long_note("# CLI Rules\n", description="CLI rules reference."),
    )

    planned = plan_bare_init_amd()

    assert ("create", tmp_path / "AGENTS.md") in planned
    for filename in PROVIDER_SHIM_FILES:
        assert ("create", tmp_path / filename) in planned


def test_bare_init_amd_apply_writes_managed_agents_without_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "AGENTS.md", "# Agent Instructions\n\n@memory/sase.md\n")
    write(tmp_path / "memory" / "sase.md", short_note("# SASE\n"))
    write(
        tmp_path / "memory" / "cli_rules.md",
        long_note("# CLI Rules\n", description="CLI rules reference."),
    )

    assert run_bare_init_amd() == 0

    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    first_line = agents.splitlines()[0]
    assert first_line.startswith("# ")
    assert first_line.endswith(" - Agent Instructions")
    assert "## Tier 1 (short-term) Memory" in agents
    assert "## Tier 2 (long-term) Memory" in agents
    assert "**`memory/cli_rules.md`**  \nCLI rules reference." in agents
    # Idempotent: the managed file is now current.
    assert plan_bare_init_amd() == set()


def test_bare_init_amd_plan_conservative_with_only_generated_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "memory" / "sase.md", short_note("# SASE\n"))

    planned = plan_bare_init_amd()

    assert planned == set()
    assert not (tmp_path / "AGENTS.md").exists()


def test_amd_init_migrates_single_legacy_provider_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    legacy = "# Legacy Instructions\n\nKeep this content.\n"
    write(tmp_path / "CLAUDE.md", legacy)

    assert ("create", tmp_path / "AGENTS.md") in plan_amd()
    assert run_amd() == 0

    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == legacy
    for filename in PROVIDER_SHIM_FILES:
        assert (tmp_path / filename).read_text(encoding="utf-8") == (
            PROVIDER_SHIM_CONTENT
        )


def test_amd_init_blocks_multiple_legacy_provider_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "CLAUDE.md", "# Claude\n")
    write(tmp_path / "GEMINI.md", "# Gemini\n")

    assert run_amd() == 1

    err = capsys.readouterr().err
    assert "multiple provider instruction files contain custom content" in err
    assert not (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "# Claude\n"
    assert (tmp_path / "GEMINI.md").read_text(encoding="utf-8") == "# Gemini\n"


def test_amd_init_blocks_shim_only_without_agents_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "CLAUDE.md", PROVIDER_SHIM_CONTENT)

    assert run_amd() == 1

    err = capsys.readouterr().err
    assert "AGENTS.md is missing" in err
    assert "provider shim files already point to it" in err
    assert not (tmp_path / "AGENTS.md").exists()


def test_amd_init_generates_managed_agents_from_project_local_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(amd_init.config_core, "CONFIG_DIR", config_dir)
    write(config_dir / "sase_athena.yml", 'amd_h1_title: "Global Title"\n')
    write(tmp_path / "sase.yml", 'amd_h1_title: "Managed Agent Instructions"\n')
    write(tmp_path / "memory" / "sase.md", short_note("# SASE\n"))
    write(tmp_path / "memory" / "extra.md", short_note("# Extra\n"))
    write(
        tmp_path / "memory" / "described.md",
        long_note("# Described\n", description="Frontmatter description."),
    )
    write(
        tmp_path / "memory" / "curated.md",
        long_note(
            "# Curated\n\nFallback body should not be used.\n",
            description=None,
        ),
    )
    write(
        tmp_path / "AGENTS.md",
        "# Previous\n\n**`memory/curated.md`**  \nCurated description survives.\n",
    )

    assert run_amd() == 0

    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Managed Agent Instructions\n")
    assert "## Tier 1 (short-term) Memory" in agents
    assert "- @memory/extra.md" in agents
    assert "- @memory/sase.md" in agents
    assert "## Tier 2 (dynamic) Memory" not in agents
    assert "## Dynamic Memory Files" not in agents
    assert "### DYNAMIC MEMORY" not in agents
    assert "## Tier 2 (long-term) Memory" in agents
    assert "## Tier 3 (long-term) Memory" not in agents
    assert "#### Long-Term Memory Files" not in agents
    assert "**`memory/described.md`**  \nFrontmatter description." in agents
    assert "**`memory/curated.md`**  \nCurated description survives." in agents
    assert ("sase-" + "amd:") not in agents
    for filename in PROVIDER_SHIM_FILES:
        assert (tmp_path / filename).read_text(encoding="utf-8") == (
            PROVIDER_SHIM_CONTENT
        )


def test_amd_init_does_not_render_dynamic_section_for_keyworded_long_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "sase.yml", 'amd_h1_title: "Managed Agent Instructions"\n')
    write(tmp_path / "memory" / "sase.md", short_note("# SASE\n"))
    write(
        tmp_path / "memory" / "dynamic.md",
        long_note(
            "# Dynamic\n",
            description="Dynamic description.",
            extra_frontmatter="keywords: [foobar facts]",
        ),
    )

    assert run_amd() == 0

    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Tier 1 (short-term) Memory" in agents
    assert "## Tier 2 (dynamic) Memory" not in agents
    assert "## Dynamic Memory Files" not in agents
    assert "## Tier 2 (long-term) Memory" in agents
    assert "## Tier 3 (long-term) Memory" not in agents
    assert "#### Long-Term Memory Files" not in agents
    assert "### DYNAMIC MEMORY" not in agents
    assert "**`memory/dynamic.md`**  \nDynamic description." in agents


def test_amd_init_ignores_global_amd_h1_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    config_dir = home / ".config" / "sase"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)
    monkeypatch.setattr(amd_init.config_core, "CONFIG_DIR", config_dir)
    write(
        config_dir / "sase_athena.yml",
        'amd_h1_title: "Global Overlay Title Must Be Ignored"\n',
    )

    assert run_amd() == 0

    assert not (project / "AGENTS.md").exists()
    for filename in PROVIDER_SHIM_FILES:
        assert (project / filename).read_text(encoding="utf-8") == (
            PROVIDER_SHIM_CONTENT
        )


def test_amd_init_manages_live_home_from_user_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    config_dir = home / ".config" / "sase"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(home)
    monkeypatch.setattr(amd_init.config_core, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(
        amd_init.config_core,
        "CHEZMOI_HOME",
        tmp_path / "chezmoi" / "home",
    )
    write(config_dir / "sase_athena.yml", 'amd_h1_title: "Athena Home"\n')
    write(home / "memory" / "sase.md", short_note("# SASE\n"))

    assert run_amd() == 0

    agents = (home / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Athena Home\n")
    assert "- @memory/sase.md" in agents
    for filename in PROVIDER_SHIM_FILES:
        assert (home / filename).read_text(encoding="utf-8") == (
            home_provider_shim_content(home)
        )


def test_amd_init_manages_chezmoi_home_from_source_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_home = tmp_path / "home"
    live_config_dir = live_home / ".config" / "sase"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    live_home.mkdir()
    chezmoi_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(live_home))
    monkeypatch.chdir(chezmoi_home)
    monkeypatch.setattr(amd_init.config_core, "CONFIG_DIR", live_config_dir)
    monkeypatch.setattr(amd_init.config_core, "CHEZMOI_HOME", chezmoi_home)
    write(live_config_dir / "sase_athena.yml", 'amd_h1_title: "Live Title"\n')
    write(
        chezmoi_home / "dot_config" / "sase" / "sase_athena.yml",
        'amd_h1_title: "Source Title"\n',
    )
    write(chezmoi_home / "memory" / "sase.md", short_note("# SASE\n"))

    assert run_amd() == 0

    agents = (chezmoi_home / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Source Title\n")
    assert "Live Title" not in agents
    for filename in PROVIDER_SHIM_FILES:
        assert (chezmoi_home / f"{filename}.tmpl").read_text(encoding="utf-8") == (
            CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT
        )
        assert not (chezmoi_home / filename).exists()


def test_amd_init_use_chezmoi_from_home_updates_source_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_home = tmp_path / "home"
    live_config_dir = live_home / ".config" / "sase"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    live_home.mkdir()
    chezmoi_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(live_home))
    monkeypatch.chdir(live_home)
    monkeypatch.setattr(amd_init.config_core, "CONFIG_DIR", live_config_dir)
    monkeypatch.setattr(amd_init.config_core, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(amd_init.config_core, "get_use_chezmoi", lambda: True)
    write(
        chezmoi_home / "dot_config" / "sase" / "sase_athena.yml",
        'amd_h1_title: "Source Home"\n',
    )
    write(chezmoi_home / "memory" / "sase.md", short_note("# SASE\n"))
    write(
        chezmoi_home / "memory" / "source.md",
        long_note("# Source\n", description="Fresh source description."),
    )
    write(
        chezmoi_home / "AGENTS.md",
        "# Source Home\n\n**`memory/source.md`**  \nStale description.\n",
    )

    assert run_amd() == 0

    agents = (chezmoi_home / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Source Home\n")
    assert "**`memory/source.md`**  \nFresh source description." in agents
    assert "Stale description." not in agents
    assert not (live_home / "AGENTS.md").exists()
    for filename in PROVIDER_SHIM_FILES:
        assert (chezmoi_home / f"{filename}.tmpl").read_text(encoding="utf-8") == (
            CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT
        )
        assert not (chezmoi_home / filename).exists()


def test_amd_init_use_chezmoi_from_project_updates_project_and_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_home = tmp_path / "home"
    project = tmp_path / "project"
    live_config_dir = live_home / ".config" / "sase"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    live_home.mkdir()
    project.mkdir()
    chezmoi_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(live_home))
    monkeypatch.chdir(project)
    monkeypatch.setattr(amd_init.config_core, "CONFIG_DIR", live_config_dir)
    monkeypatch.setattr(amd_init.config_core, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(amd_init.config_core, "get_use_chezmoi", lambda: True)
    write(project / "sase.yml", 'amd_h1_title: "Project Instructions"\n')
    write(project / "memory" / "sase.md", short_note("# Project SASE\n"))
    write(
        project / "memory" / "project.md",
        long_note("# Project\n", description="Project description."),
    )
    write(
        chezmoi_home / "dot_config" / "sase" / "sase_athena.yml",
        'amd_h1_title: "Source Home"\n',
    )
    write(chezmoi_home / "memory" / "sase.md", short_note("# Home SASE\n"))
    write(
        chezmoi_home / "memory" / "source.md",
        long_note("# Source\n", description="Source description."),
    )

    assert run_amd() == 0

    project_agents = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert project_agents.startswith("# Project Instructions\n")
    assert "**`memory/project.md`**  \nProject description." in project_agents
    source_agents = (chezmoi_home / "AGENTS.md").read_text(encoding="utf-8")
    assert source_agents.startswith("# Source Home\n")
    assert "**`memory/source.md`**  \nSource description." in source_agents
    for filename in PROVIDER_SHIM_FILES:
        assert (project / filename).read_text(encoding="utf-8") == (
            PROVIDER_SHIM_CONTENT
        )
        assert (chezmoi_home / f"{filename}.tmpl").read_text(encoding="utf-8") == (
            CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT
        )
        assert not (chezmoi_home / filename).exists()


def test_amd_init_refreshes_old_live_home_provider_shim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(amd_init.config_core, "get_use_chezmoi", lambda: False)
    monkeypatch.chdir(home)
    write(home / "AGENTS.md", "# Home Instructions\n")
    write(home / "CLAUDE.md", PROVIDER_SHIM_CONTENT)

    planned = plan_amd()

    assert ("overwrite", home / "CLAUDE.md") in planned
    assert run_amd() == 0
    assert (home / "CLAUDE.md").read_text(encoding="utf-8") == (
        home_provider_shim_content(home)
    )


def test_amd_check_reports_chezmoi_template_migration_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_home = tmp_path / "home"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    live_home.mkdir()
    chezmoi_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(live_home))
    monkeypatch.setattr(amd_init.config_core, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.chdir(chezmoi_home)
    write(chezmoi_home / "AGENTS.md", "# Chezmoi Instructions\n")
    write(chezmoi_home / "CLAUDE.md", HOME_PROVIDER_SHIM_CONTENT)

    planned = plan_amd()

    assert ("create", chezmoi_home / "CLAUDE.md.tmpl") in planned
    assert ("delete", chezmoi_home / "CLAUDE.md") in planned
    assert run_amd(check=True) == 1
    assert (chezmoi_home / "CLAUDE.md").read_text(encoding="utf-8") == (
        HOME_PROVIDER_SHIM_CONTENT
    )
    assert not (chezmoi_home / "CLAUDE.md.tmpl").exists()


def test_amd_init_migrates_chezmoi_plain_shims_to_templates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_home = tmp_path / "home"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    live_home.mkdir()
    chezmoi_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(live_home))
    monkeypatch.setattr(amd_init.config_core, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.chdir(chezmoi_home)
    write(chezmoi_home / "AGENTS.md", "# Chezmoi Instructions\n")
    write(chezmoi_home / "CLAUDE.md", HOME_PROVIDER_SHIM_CONTENT)

    assert run_amd() == 0

    for filename in PROVIDER_SHIM_FILES:
        assert (chezmoi_home / f"{filename}.tmpl").read_text(
            encoding="utf-8"
        ) == CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT
    assert not (chezmoi_home / "CLAUDE.md").exists()


@pytest.mark.parametrize("cwd_name", ("home", "project"))
def test_amd_check_use_chezmoi_reports_source_drift_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cwd_name: str,
) -> None:
    live_home = tmp_path / "home"
    project = tmp_path / "project"
    live_config_dir = live_home / ".config" / "sase"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    live_home.mkdir()
    project.mkdir()
    chezmoi_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(live_home))
    monkeypatch.setattr(amd_init.config_core, "CONFIG_DIR", live_config_dir)
    monkeypatch.setattr(amd_init.config_core, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(amd_init.config_core, "get_use_chezmoi", lambda: True)
    write(
        chezmoi_home / "dot_config" / "sase" / "sase_athena.yml",
        'amd_h1_title: "Source Home"\n',
    )
    write(chezmoi_home / "memory" / "sase.md", short_note("# SASE\n"))
    write(
        chezmoi_home / "memory" / "source.md",
        long_note("# Source\n", description="Fresh source description."),
    )
    stale_agents = "# Source Home\n\n**`memory/source.md`**  \nStale description.\n"
    write(chezmoi_home / "AGENTS.md", stale_agents)
    write_provider_shim_templates(chezmoi_home)
    if cwd_name == "project":
        write(project / "AGENTS.md", "# Project\n")
        write_provider_shims(project)
        monkeypatch.chdir(project)
    else:
        monkeypatch.chdir(live_home)

    assert run_amd(check=True) == 1

    assert (chezmoi_home / "AGENTS.md").read_text(encoding="utf-8") == stale_agents
    out = capsys.readouterr().out
    assert "SASE initialization check" in out
    assert "Needs attention:" in out
    assert str(chezmoi_home / "AGENTS.md") in out
