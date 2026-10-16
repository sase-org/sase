"""Tests for managed AGENTS memory generation and inline rendering."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

import sase.config.core as config_core
from tests.main.init_memory_handler_helpers import (
    long_note,
    patch_standard_paths,
    plan_memory,
    prettier_command,
    run_handler,
    short_note,
    write,
)


def test_init_memory_syncs_amd_agents_and_long_memory_descriptions(
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
        'is_sase_managed: true\nmemory:\n  h1_title: "Managed Instructions"\n',
    )
    write(
        project_root / "sase" / "memory" / "extra.md",
        short_note("# Extra\n\n## Section\n"),
    )
    write(
        project_root / "sase" / "memory" / "described.md",
        long_note(
            "# Described\n",
            description="Existing description.",
            extra_frontmatter="keywords:\n  - existing\nowner: docs",
        ),
    )
    write(
        project_root / "sase" / "memory" / "curated.md",
        long_note(
            "# Curated\n\nFallback body should not be used.\n",
            description=None,
        ),
    )
    write(
        project_root / "AGENTS.md",
        "# Previous\n\n"
        "**`sase/memory/curated.md`**  \n"
        "Curated description survives. _Read when touching curated memory._\n",
    )

    assert run_handler() == 0

    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Managed Instructions\n")
    assert "## 1. Core Memory" in agents
    assert "The following memories contain core (always loaded) context:" in agents
    # Short memory is inlined (no ``@sase/memory/...`` imports) under H3 headers.
    assert "### 1.1 SASE = Structured Agentic Software Engineering (sase)" in agents
    assert "#### 1.1.1 SASE Memory" in agents
    assert "### 1.2 Extra (extra)" in agents
    assert "#### 1.2.1 Section" in agents
    assert "@sase/memory/extra.md" not in agents
    assert "@sase/memory/sase.md" not in agents
    assert "## Tier 2 (dynamic) Memory" not in agents
    assert "## Dynamic Memory Files" not in agents
    assert "### DYNAMIC MEMORY" not in agents
    assert "## 2. Reference Memory" in agents
    assert "## Tier 3 (reference) Memory" not in agents
    assert "Long-Term Memory Files" not in agents
    assert "Glossary Terms" not in agents
    assert "1. **`sase/memory/curated.md`** - Curated description survives." in agents
    assert "2. **`sase/memory/described.md`** - Existing description." in agents
    assert "## 3. Memory Webs" in agents
    assert "### 3.1 Task Bead Types (task_types)" in agents
    assert ("sase-" + "amd:") not in agents

    generated_sase = (project_root / "sase" / "memory" / "sase.md").read_text(
        encoding="utf-8"
    )
    assert generated_sase.startswith(
        "---\ntype: core\nparent: AGENTS.md\npriority: 10\n---\n"
    )

    curated = (project_root / "sase" / "memory" / "curated.md").read_text(
        encoding="utf-8"
    )
    assert curated.startswith(
        "---\n"
        "type: reference\n"
        "parent: AGENTS.md\n"
        "description: Curated description survives.\n"
        "---\n"
    )
    described = (project_root / "sase" / "memory" / "described.md").read_text(
        encoding="utf-8"
    )
    assert "description: Existing description." in described
    assert "keywords:" not in described
    assert "owner: docs" in described

    # The inlined managed AGENTS.md must stay prettier-stable.
    agents_path = project_root / "AGENTS.md"
    assert agents_path.read_bytes().endswith(b"\n")
    result = subprocess.run(
        [
            *prettier_command(),
            "--check",
            str(agents_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"prettier --check failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_init_memory_managed_agents_inline_short_memory_is_single_pass_idempotent(
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
        'is_sase_managed: true\nmemory:\n  h1_title: "Managed Instructions"\n',
    )
    write(
        project_root / "sase" / "memory" / "described.md",
        long_note("# Described\n", description="A long note."),
    )

    assert run_handler() == 0

    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "### 1.1 SASE = Structured Agentic Software Engineering (sase)" in agents
    assert "@sase/memory/sase.md" not in agents

    # ``sase/memory/sase.md`` is regenerated every run, and its *fresh* body is the one
    # inlined into ``AGENTS.md``; a follow-up plan must therefore be a no-op.
    plan = plan_memory()
    assert plan.blockers == ()
    assert plan.actions == ()


def test_projection_header_is_project_only_and_prettier_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The project AGENTS.md carries the header; the home one never does."""
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
        project_root / "sase.yml",
        'is_sase_managed: true\nmemory:\n  h1_title: "Managed Instructions"\n',
    )
    write(
        project_root / "sase" / "memory" / "extra.md",
        short_note("# Extra\n\n## Section\n"),
    )
    write(config_dir / "sase.yml", 'memory:\n  h1_title: "Home Instructions"\n')

    assert run_handler() == 0

    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith(
        "# Managed Instructions\n"
        "\n"
        "> This file is generated from `sase/memory/` by `sase memory init`;"
    )
    assert "`sase instructions render`" in agents
    assert "`sase instructions show NAME`" in agents
    assert "## 1. Core Memory" in agents

    home_agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    assert home_agents.startswith("# Home Instructions\n")
    assert "generated from `sase/memory/`" not in home_agents
    assert "sase instructions show NAME" not in home_agents

    for path in (project_root / "AGENTS.md", home_root / "AGENTS.md"):
        result = subprocess.run(
            [*prettier_command(), "--check", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"prettier --check failed for {path}:\nstdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
