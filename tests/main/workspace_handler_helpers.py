"""Shared helpers for ``sase workspace`` handler tests."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from collections.abc import Mapping

import pytest
import yaml

from sase._linked_repo_config import reset_linked_repo_config_caches
from sase.config.core import clear_config_cache
from sase.content_layout import resolve_project_config_write_path


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
    write_project_local_config(primary, fake_config, monkeypatch=monkeypatch)
    monkeypatch.setattr(
        "sase.main.workspace_handler.load_merged_config",
        lambda: fake_config,
    )
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: fake_config,
    )
    return project_name, str(project_file), primary


def write_project_local_config(
    workspace: Path,
    config: Mapping[str, Any],
    *,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> Path:
    """Write *config* at the target project's canonical ``sase/sase.yml``.

    Repository resolution now loads config for the target workspace instead of
    the process cwd, so tests that previously patched ``load_merged_config``
    still need a realistic project-local file.
    """

    if monkeypatch is not None:
        config_dir = workspace.parent / "empty-sase-config"
        config_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("sase.config.core.CONFIG_DIR", config_dir)
    path = resolve_project_config_write_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(dict(config)), encoding="utf-8")
    reset_linked_repo_config_caches()
    clear_config_cache()
    return path


def make_args(**overrides: object) -> argparse.Namespace:
    return argparse.Namespace(**overrides)
