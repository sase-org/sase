"""Tests for prompt-derived completion roots."""

from __future__ import annotations

import re
from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch

from sase.ace.tui.widgets.prompt_completion_root import (
    resolve_prompt_completion_base_dir,
)
from sase.workspace_provider import ResolvedRef
from tests._workspace_provider_helpers import patch_git_metadata


def test_git_completion_root_uses_known_projects_without_provider_resolution(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    patch_git_metadata(monkeypatch)
    workspace = tmp_path / "bob-cli"
    workspace.mkdir()
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda include_states=("enabled",): {"bob-cli": workspace},
    )

    def fail_resolve_ref(ref: str, workflow_type: str) -> object:
        raise AssertionError("resolve_ref should not be called for #git completion")

    monkeypatch.setattr("sase.workspace_provider.resolve_ref", fail_resolve_ref)

    assert resolve_prompt_completion_base_dir("#git:bob-cli sdd/") == str(workspace)


def test_registered_completion_root_uses_peek_ref_not_resolve_ref(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    pattern = re.compile(r"(?:^|(?<=\s))#spy[_:]([^\s]+)")
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "sase.workspace_provider.get_ref_patterns", lambda: {"spy": pattern}
    )

    def fail_resolve_ref(ref: str, workflow_type: str) -> object:
        raise AssertionError("resolve_ref should not be called for completion")

    def peek_ref(ref: str, workflow_type: str) -> ResolvedRef | None:
        calls.append((ref, workflow_type))
        return ResolvedRef(
            project_file="/tmp/repo.sase",
            project_name="repo",
            primary_workspace_dir=str(workspace),
            checkout_target="origin/main",
        )

    monkeypatch.setattr("sase.workspace_provider.resolve_ref", fail_resolve_ref)
    monkeypatch.setattr("sase.workspace_provider.peek_ref", peek_ref)

    assert resolve_prompt_completion_base_dir("#spy:owner/repo src/") == str(workspace)
    assert calls == [("owner/repo", "spy")]


def test_registered_completion_root_falls_back_to_known_project_when_peek_is_none(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    pattern = re.compile(r"(?:^|(?<=\s))#spy[_:]([^\s]+)")

    monkeypatch.setattr(
        "sase.workspace_provider.get_ref_patterns", lambda: {"spy": pattern}
    )
    monkeypatch.setattr("sase.workspace_provider.peek_ref", lambda _ref, _wf: None)
    monkeypatch.setattr(
        "sase.workspace_provider.resolve_ref",
        lambda _ref, _wf: (_ for _ in ()).throw(
            AssertionError("resolve_ref should not be called for completion")
        ),
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda include_states=("enabled",): {"repo": workspace},
    )

    assert resolve_prompt_completion_base_dir("#spy:repo src/") == str(workspace)
