"""Tests for prompt-derived completion roots."""

from __future__ import annotations

import re
from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch

from sase import project_alias_prompts
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


def test_warm_completion_root_does_not_reread_project_alias_files(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    patch_git_metadata(monkeypatch)
    with project_alias_prompts._PROJECT_LOOKUP_CACHE_LOCK:
        project_alias_prompts._WORKFLOW_TYPE_CACHE.clear()
        project_alias_prompts._CHANGESPEC_NAMES_CACHE.clear()

    project = "git_sase-org__sase"
    workspace = tmp_path / "sase"
    workspace.mkdir()
    project_file = tmp_path / "sase.sase"
    project_file.write_text(
        "PROJECT_ALIASES: sase\nWORKSPACE_DIR: /tmp/sase\nNAME: existing\n",
        encoding="utf-8",
    )
    reads = {"changespec_names": 0, "workflow_type": 0}

    def project_file_signature(
        project_name: str,
    ) -> tuple[str, int, int] | None:
        assert project_name == project
        stat_result = project_file.stat()
        return (str(project_file), stat_result.st_mtime_ns, stat_result.st_size)

    def load_changespec_names(project_name: str) -> frozenset[str]:
        assert project_name == project
        reads["changespec_names"] += 1
        project_file.read_text(encoding="utf-8")
        return frozenset({"sase_fix"})

    def project_workflow_type(project_name: str) -> str | None:
        assert project_name == project
        reads["workflow_type"] += 1
        project_file.read_text(encoding="utf-8")
        return "git"

    def fail_resolve_ref(ref: str, workflow_type: str) -> object:
        raise AssertionError(
            f"resolve_ref should not run for {workflow_type}:{ref} completion"
        )

    monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"git"})
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda *_args, **_kwargs: {"sase": project},
    )
    monkeypatch.setattr(
        "sase.project_aliases._load_project_changespec_names",
        load_changespec_names,
    )
    monkeypatch.setattr(
        "sase.project_aliases._project_workflow_type",
        project_workflow_type,
    )
    monkeypatch.setattr(
        "sase.project_aliases._load_project_changespec_names_cache_signature",
        lambda project_name: (project_file_signature(project_name), None),
    )
    monkeypatch.setattr(
        "sase.project_aliases._project_workflow_type_cache_signature",
        project_file_signature,
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda include_states=("enabled",): {project: workspace},
    )
    monkeypatch.setattr("sase.workspace_provider.peek_ref", lambda _ref, _wf: None)
    monkeypatch.setattr("sase.workspace_provider.resolve_ref", fail_resolve_ref)
    prompt = "#git:sase_fix review #git:sase src/"

    assert resolve_prompt_completion_base_dir(prompt) == str(workspace)
    assert reads == {"changespec_names": 1, "workflow_type": 1}
    assert resolve_prompt_completion_base_dir(prompt) == str(workspace)
    assert reads == {"changespec_names": 1, "workflow_type": 1}


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
