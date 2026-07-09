"""Shared workspace-provider metadata helpers for tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.workspace_provider._hookspec import ResolvedRef, WorkflowMetadata


def _reset_xprompt_vcs_caches() -> None:
    import sase.xprompt._parsing as parsing
    import sase.xprompt._parsing_vcs_refs as vcs_refs
    import sase.xprompt._parsing_vcs_tags as vcs_tags

    parsing._VCS_TAG_PATTERN = None
    parsing._VCS_TAG_EMBEDDED_PATTERN = None
    parsing._VCS_REPLACE_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_EMBEDDED_PATTERN = None
    vcs_tags._VCS_REPLACE_PATTERN = None
    vcs_refs._VCS_UNDERSCORE_NORMALIZER = None
    vcs_refs._LAUNCH_XPROMPT_AT_REF_RE = None


def git_metadata() -> tuple[WorkflowMetadata, ...]:
    return (
        WorkflowMetadata(
            workflow_type="git",
            ref_pattern=r"(?:^|(?<=\s))#git(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="Git",
            pre_allocated_env_prefix="SASE_GIT",
        ),
    )


def no_workspace_metadata() -> tuple[WorkflowMetadata, ...]:
    return ()


def patch_git_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", git_metadata)
    _reset_xprompt_vcs_caches()


def patch_no_workspace_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", no_workspace_metadata)
    _reset_xprompt_vcs_caches()


def patch_simple_git_resolver(
    monkeypatch: pytest.MonkeyPatch,
    base: Path,
) -> None:
    def resolve_ref(ref: str, workflow_type: str) -> ResolvedRef:
        if workflow_type != "git":
            raise ValueError(f"unexpected workflow type: {workflow_type}")
        workspace_dir = base / ref
        return ResolvedRef(
            project_file=str(base / f"{ref}.sase"),
            project_name=ref,
            primary_workspace_dir=str(workspace_dir),
            checkout_target="main",
        )

    monkeypatch.setattr("sase.workspace_provider.resolve_ref", resolve_ref)
