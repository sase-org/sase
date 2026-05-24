"""Tests for ``sase amd init`` planning and application."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.amd.constants import (
    LONG_MEMORY_END_MARKER,
    LONG_MEMORY_START_MARKER,
    PROVIDER_SHIM_CONTENT,
    PROVIDER_SHIM_FILES,
    SHORT_MEMORY_END_MARKER,
    SHORT_MEMORY_START_MARKER,
)
from sase.amd.init import _build_amd_init_plan, run_amd_init


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_amd(*, check: bool = False) -> int:
    return run_amd_init(argparse.Namespace(check=check))


def plan_amd() -> set[tuple[str, Path]]:
    plan = _build_amd_init_plan().plan
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
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "sase.yml", 'amd_h1_title: "Managed Agent Instructions"\n')
    write(tmp_path / "memory" / "short" / "sase.md", "# SASE\n")
    write(tmp_path / "memory" / "short" / "extra.md", "# Extra\n")
    write(
        tmp_path / "memory" / "long" / "described.md",
        "---\ndescription: Frontmatter description.\n---\n# Described\n",
    )
    write(
        tmp_path / "memory" / "long" / "curated.md",
        "# Curated\n\nFallback body should not be used.\n",
    )
    write(
        tmp_path / "AGENTS.md",
        "# Previous\n\n**`memory/long/curated.md`**  \nCurated description survives.\n",
    )

    assert run_amd() == 0

    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Managed Agent Instructions\n")
    assert SHORT_MEMORY_START_MARKER in agents
    assert "- @memory/short/extra.md" in agents
    assert "- @memory/short/sase.md" in agents
    assert SHORT_MEMORY_END_MARKER in agents
    assert LONG_MEMORY_START_MARKER in agents
    assert "**`memory/long/described.md`**  \nFrontmatter description." in agents
    assert "**`memory/long/curated.md`**  \nCurated description survives." in agents
    assert LONG_MEMORY_END_MARKER in agents
    for filename in PROVIDER_SHIM_FILES:
        assert (tmp_path / filename).read_text(encoding="utf-8") == (
            PROVIDER_SHIM_CONTENT
        )


def test_amd_init_ignores_global_amd_h1_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)
    write(
        home / ".config" / "sase" / "sase.yml",
        'amd_h1_title: "Global Title Must Be Ignored"\n',
    )

    assert run_amd() == 0

    assert not (project / "AGENTS.md").exists()
    for filename in PROVIDER_SHIM_FILES:
        assert (project / filename).read_text(encoding="utf-8") == (
            PROVIDER_SHIM_CONTENT
        )
