"""Tests for managed AGENTS memory description rendering and recovery."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.amd._agents_doc import parse_amd_agents_document
from sase.amd._memory import _existing_agents_long_descriptions
from tests.main.init_memory_handler_helpers import (
    long_note,
    patch_standard_paths,
    plan_memory,
    prettier_command,
    run_handler,
    write,
)


def test_init_memory_managed_agents_wraps_long_memory_descriptions(
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
        project_root / "sase" / "memory" / "generated_skills.md",
        long_note(
            "# Generated Skills\n",
            description=(
                "Read when working with sase agent skills (aka xprompt skills), "
                "which are generated from source templates in the "
                "`src/sase/xprompts/skills/` and deployed to managed locations "
                "(my chezmoi repo, for example)."
            ),
        ),
    )

    assert run_handler() == 0

    agents_path = project_root / "AGENTS.md"
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

    plan = plan_memory()
    assert plan.blockers == ()
    assert plan.actions == ()


def test_init_memory_managed_agents_renders_block_long_memory_descriptions(
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
        project_root / "sase" / "memory" / "block.md",
        "---\n"
        "type: reference\n"
        "parent: AGENTS.md\n"
        "description: |-\n"
        "  Lead paragraph.\n"
        "\n"
        "  - One\n"
        "  - Two\n"
        "\n"
        "  Trailer.\n"
        "---\n"
        "# Block\n",
    )

    assert run_handler() == 0

    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert (
        "### 2.1 `sase/memory/block.md`\n\n"
        "Lead paragraph.\n\n- One\n- Two\n\nTrailer.\n"
    ) in agents
    parsed = parse_amd_agents_document(agents)
    expected_paths = (
        "sase/memory/block.md",
        "sase/memory/sase_artifacts.md",
        "sase/memory/sase_beads.md",
    )
    assert tuple(entry.path for entry in parsed.long_memory_entries) == expected_paths
    block_entry = parsed.long_memory_entries[0]
    assert block_entry.description == "Lead paragraph.\n\n- One\n- Two\n\nTrailer."
    assert plan_memory().actions == ()


def test_existing_agents_long_descriptions_preserves_legacy_block_descriptions(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    write(
        root / "AGENTS.md",
        "# Legacy\n\n"
        "**`memory/block.md`**  \n"
        "Lead paragraph.\n"
        "\n"
        "- One\n"
        "\n"
        "Trailer. _Read when touching block memory._\n"
        "\n"
        "**`memory/next.md`**  \n"
        "Next description.\n",
    )

    assert _existing_agents_long_descriptions(root) == {
        "sase/memory/block.md": "Lead paragraph.\n\n- One\n\nTrailer.",
        "sase/memory/next.md": "Next description.",
    }


def test_existing_agents_long_descriptions_reads_section_shape_without_anchor(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    write(
        root / "AGENTS.md",
        "# Custom\n\n"
        "### `sase/memory/block.md`\n\n"
        "Lead paragraph.\n"
        "\n"
        "- One\n"
        "\n"
        "Trailer. _Read when touching block memory._\n"
        "\n"
        "### 2.2 `memory/next.md`\n\n"
        "Next description.\n"
        "\n"
        "## Other\n"
        "Should not be part of the description.\n",
    )

    assert _existing_agents_long_descriptions(root) == {
        "sase/memory/block.md": "Lead paragraph.\n\n- One\n\nTrailer.",
        "sase/memory/next.md": "Next description.",
    }


def test_init_memory_rejects_long_memory_description_with_heading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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
        project_root / "sase" / "memory" / "foo.md",
        "---\n"
        "type: reference\n"
        "parent: AGENTS.md\n"
        "description: |-\n"
        "  Intro.\n"
        "\n"
        "  ## Heading\n"
        "\n"
        "  More.\n"
        "---\n"
        "# Foo\n",
    )

    assert run_handler() == 1
    err = capsys.readouterr().err
    assert "sase/memory/foo.md" in err
    assert "must not contain Markdown headings" in err


def test_init_memory_allows_fenced_hash_in_long_memory_description(
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
        project_root / "sase" / "memory" / "foo.md",
        "---\n"
        "type: reference\n"
        "parent: AGENTS.md\n"
        "description: |-\n"
        "  Intro.\n"
        "\n"
        "  ```\n"
        "  # comment\n"
        "  ```\n"
        "\n"
        "  More.\n"
        "---\n"
        "# Foo\n",
    )

    assert run_handler() == 0
    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "### 2.1 `sase/memory/foo.md`" in agents
    assert "# comment" in agents
    assert plan_memory().blockers == ()
