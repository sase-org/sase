"""Tests for managed AGENTS provider shim synchronization."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.amd.constants import PROVIDER_SHIM_FILES
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    run_handler,
    write,
)


def test_init_memory_overwrites_provider_shims(
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
    write(project_root / "AGENTS.md", "@sase/memory/sase.md\n")
    write(project_root / "CLAUDE.md", "old instructions\n")

    assert run_handler() == 0

    # Every provider file is overwritten with a byte-for-byte copy of AGENTS.md.
    agents = (project_root / "AGENTS.md").read_text()
    for filename in PROVIDER_SHIM_FILES:
        assert (project_root / filename).read_text() == agents
