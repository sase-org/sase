"""Tests for managed AGENTS memory reference resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.main.init_memory_handler_helpers import (
    long_note,
    patch_standard_paths,
    run_handler,
    write,
)


def test_init_memory_allows_transitive_memory_references(
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
        project_root / "AGENTS.md",
        "@sase/memory/sase.md\n\nsase/memory/index.md\n",
    )
    write(
        project_root / "sase" / "memory" / "index.md",
        long_note("# Index\n\n@sase/memory/detail.md\n", description="Index."),
    )
    write(
        project_root / "sase" / "memory" / "detail.md",
        long_note("# Detail\n", description="Detail."),
    )

    assert run_handler() == 0
