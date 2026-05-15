"""Shared helpers for ``sase workspace`` handler tests."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest


@pytest.fixture
def project_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str, Path]:
    """Set up a fake project rooted under ``~/.sase/projects/<name>``.

    Returns ``(project_name, project_file, primary_workspace_dir)``.  Uses
    an absolute managed root so the registry-backed code paths are
    exercised end-to-end.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
    sase_dir = tmp_path / "home" / ".sase" / "projects"
    primary = tmp_path / "primary"
    primary.mkdir()
    project_name = "demo"
    project_dir = sase_dir / project_name
    project_dir.mkdir(parents=True)
    project_file = project_dir / f"{project_name}.sase"
    project_file.write_text(f"WORKSPACE_DIR: {primary}\n", encoding="utf-8")

    managed_root = tmp_path / "managed"
    fake_config = {
        "workspace": {
            "root": str(managed_root),
            "project_key": "demo-key",
            "cleanup_ttl_days": 1,
        }
    }
    monkeypatch.setattr(
        "sase.main.workspace_handler.load_merged_config",
        lambda: fake_config,
    )
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: fake_config,
    )
    return project_name, str(project_file), primary


def make_args(**overrides: object) -> argparse.Namespace:
    return argparse.Namespace(**overrides)
