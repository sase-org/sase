"""Tests for generated ``sase memory init`` markdown formatting."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.main.init_memory.formatting import format_generated_memory_markdown
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    prettier_command,
    run_memory,
    write,
)


def test_init_memory_plan_empty_after_prettier_formats_generated_files(
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
        """
is_sase_managed: true
linked_repos:
  - name: core
    path: ../sase-core
    description: Shared Rust core backend for SASE domain behavior and cross-frontend APIs.
""",
    )

    assert run_memory() == 0

    generated = [
        project_root / "memory" / "sase.md",
        project_root / "memory" / "README.md",
        home_root / "memory" / "sase.md",
        home_root / "memory" / "README.md",
    ]
    before = {path: path.read_text(encoding="utf-8") for path in generated}
    result = subprocess.run(
        [
            *prettier_command(),
            "--write",
            "--prose-wrap=always",
            "--print-width=120",
            *[str(path) for path in generated],
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"prettier --write failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert {path: path.read_text(encoding="utf-8") for path in generated} == before

    plan = plan_memory()
    assert plan.actions == ()
    assert plan.blockers == ()


def test_init_memory_generated_markdown_passes_prettier_check(
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

    assert run_memory() == 0

    generated = [
        project_root / "memory" / "sase.md",
        project_root / "memory" / "README.md",
    ]
    assert all(path.read_bytes().endswith(b"\n") for path in generated)
    result = subprocess.run(
        [
            *prettier_command(),
            "--check",
            "--prose-wrap=always",
            "--print-width=120",
            *[str(path) for path in generated],
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"prettier --check failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_format_adds_hard_break_for_bold_label_description() -> None:
    assert (
        format_generated_memory_markdown("**`memory/foo.md`**\nRead this note.\n")
        == "**`memory/foo.md`**  \nRead this note.\n"
    )


def test_format_preserves_bold_label_followed_by_blank_line() -> None:
    assert (
        format_generated_memory_markdown("**Xprompt swarm**\n\nAn xprompt body.\n")
        == "**Xprompt swarm**\n\nAn xprompt body.\n"
    )
