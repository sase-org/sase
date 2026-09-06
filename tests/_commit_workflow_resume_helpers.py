"""Shared helpers for CommitWorkflow.resume() tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from sase.workflows.commit import checkpoint

PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"


def make_resume_provider(
    *,
    head_subject: str = "fix: bug",
    head_message: str | None = None,
    is_conflict: bool = False,
    finalize_result: tuple[bool, str | None] = (True, None),
    finalize_raises: bool = False,
    amend_result: tuple[bool, str | None] = (True, None),
) -> MagicMock:
    """Build a VCS provider mock with standard resume behavior."""
    provider = MagicMock()
    provider._provider_name = "git"
    provider.is_sync_in_progress.return_value = is_conflict
    provider.get_conflicted_files.return_value = ["a.py"] if is_conflict else []
    full_message = head_subject if head_message is None else head_message

    def _get_description(
        _revision: str, _cwd: str, *, short: bool = False
    ) -> tuple[bool, str]:
        return (True, head_subject if short else full_message)

    provider.get_description.side_effect = _get_description
    provider.amend.return_value = amend_result
    if finalize_raises:
        provider.finalize_commit.side_effect = NotImplementedError
    else:
        provider.finalize_commit.return_value = finalize_result
    return provider


def save_resume_checkpoint(
    *,
    cwd: str,
    method: str = "create_commit",
    payload: dict | None = None,
    completed_steps: list[str] | None = None,
    cl_name: str | None = None,
    project_file: str | None = None,
    cs_name: str | None = None,
    entry_id: str | None = None,
    dispatch_result: str | None = None,
    publication_agent: str | None = None,
    primary_revision: str | None = None,
    no_commit_dispatched: bool = False,
) -> checkpoint.CommitCheckpoint:
    """Persist a resume checkpoint with concise test-friendly defaults."""
    cp = checkpoint.CommitCheckpoint(
        method=method,
        payload=payload if payload is not None else {"message": "fix: bug"},
        cwd=cwd,
        completed_steps=list(completed_steps) if completed_steps else [],
        cl_name=cl_name,
        project_file=project_file,
        cs_name=cs_name,
        entry_id=entry_id,
        dispatch_result=dispatch_result,
        publication_agent=publication_agent,
        primary_revision=primary_revision,
        no_commit_dispatched=no_commit_dispatched,
    )
    checkpoint.checkpoint_save(cp)
    return cp
