"""Shared workspace-provider metadata helpers for tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.workspace_provider import reset_workflow_metadata_caches
from sase.workspace_provider._hookspec import ResolvedRef, WorkflowMetadata


class _TeardownResetTrigger:
    """Fires ``reset_workflow_metadata_caches()`` when ``monkeypatch`` undoes.

    ``pytest.MonkeyPatch`` has no public API to schedule an arbitrary
    teardown callback -- only attribute restore. Patching this sentinel's
    ``marker`` attribute turns that restore-on-undo into the missing hook:
    :meth:`__setattr__` fires both when the attribute is patched and again
    when ``monkeypatch.undo()`` restores it at test teardown, so the caches
    reset at setup get reset again once the test's fake metadata patch is
    gone, instead of staying compiled from it.
    """

    marker: object | None = None

    def __setattr__(self, name: str, value: object) -> None:
        object.__setattr__(self, name, value)
        reset_workflow_metadata_caches()


_teardown_reset_trigger = _TeardownResetTrigger()


def _restore_xprompt_vcs_caches_on_teardown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the derived VCS caches again once *monkeypatch* undoes."""
    monkeypatch.setattr(_teardown_reset_trigger, "marker", object())


def git_metadata() -> tuple[WorkflowMetadata, ...]:
    return (
        WorkflowMetadata(
            workflow_type="git",
            ref_pattern=r"(?:^|(?<=\s))#git(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="Git",
            pre_allocated_env_prefix="SASE_GIT",
        ),
    )


def spy_metadata() -> tuple[WorkflowMetadata, ...]:
    """Return metadata for a deliberately provider-neutral test workflow."""
    return (
        WorkflowMetadata(
            workflow_type="spy",
            ref_pattern=(r"(?:^|(?<=\s))#spy(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))"),
            display_name="Spy",
            pre_allocated_env_prefix="SASE_SPY",
            vcs_family="spy",
            vcs_provider_name="spy",
        ),
    )


def no_workspace_metadata() -> tuple[WorkflowMetadata, ...]:
    return ()


def patch_git_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.workspace_provider as workspace_provider
    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", git_metadata)
    monkeypatch.setattr(workspace_provider, "get_all_workflow_metadata", git_metadata)
    reset_workflow_metadata_caches()
    _restore_xprompt_vcs_caches_on_teardown(monkeypatch)


def patch_spy_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.workspace_provider as workspace_provider
    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", spy_metadata)
    monkeypatch.setattr(workspace_provider, "get_all_workflow_metadata", spy_metadata)
    reset_workflow_metadata_caches()
    _restore_xprompt_vcs_caches_on_teardown(monkeypatch)


def patch_no_workspace_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.workspace_provider as workspace_provider
    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", no_workspace_metadata)
    monkeypatch.setattr(
        workspace_provider,
        "get_all_workflow_metadata",
        no_workspace_metadata,
    )
    reset_workflow_metadata_caches()
    _restore_xprompt_vcs_caches_on_teardown(monkeypatch)


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
