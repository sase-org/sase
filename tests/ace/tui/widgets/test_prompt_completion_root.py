"""Tests for prompt-derived completion roots."""

from __future__ import annotations

from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch

from sase.ace.tui.widgets.prompt_completion_root import (
    resolve_prompt_completion_base_dir,
)
from tests._cd_launch_resolution_helpers import patch_cd_git_metadata


def test_git_completion_root_uses_known_projects_without_provider_resolution(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    patch_cd_git_metadata(monkeypatch)
    workspace = tmp_path / "bob-cli"
    workspace.mkdir()
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda include_states=("active",): {"bob-cli": workspace},
    )

    def fail_resolve_ref(ref: str, workflow_type: str) -> object:
        raise AssertionError("resolve_ref should not be called for #git completion")

    monkeypatch.setattr("sase.workspace_provider.resolve_ref", fail_resolve_ref)

    assert resolve_prompt_completion_base_dir("#git:bob-cli sdd/") == str(workspace)
