"""Workspace marker handling in main entry utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main.utils import ensure_project_file_and_get_workspace_num
from sase.workspace_provider.marker import write_marker
from sase.workspace_provider.store import WorkspaceStore


def test_project_info_uses_managed_checkout_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    project_name = "demo"
    primary = tmp_path / "primary"
    primary.mkdir()
    project_dir = tmp_path / "home" / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    project_file = project_dir / f"{project_name}.sase"
    project_file.write_text(f"WORKSPACE_DIR: {primary}\n", encoding="utf-8")

    store = WorkspaceStore(
        str(primary),
        config={
            "workspace": {
                "root": str(tmp_path / "managed"),
                "project_key": "demo-key",
            }
        },
        env={},
    )
    checkout = Path(store.resolve(10).checkout_dir.rstrip("/"))
    checkout.mkdir(parents=True)
    write_marker(store, store.resolve(10), project_name=project_name)

    nested = checkout / "src"
    nested.mkdir()
    monkeypatch.chdir(nested)

    assert ensure_project_file_and_get_workspace_num() == (
        str(project_file),
        10,
        project_name,
    )
