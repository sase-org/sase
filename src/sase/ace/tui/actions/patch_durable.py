"""Shared durable submission helper for ACE Patch actions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sase.ace.tui.durable_ops import (
    operation_fingerprint,
    patch_concurrency_key,
    sase_command_argv,
    workspace_claim_policy,
)
from sase.ops.names import (
    PATCH_ACCEPT,
    PATCH_ARCHIVE,
    PATCH_MAIL,
    PATCH_REBASE,
    PATCH_RESTORE,
    PATCH_REVERT,
    PATCH_REWIND,
    PATCH_REWORD,
    PATCH_STATUS,
    PATCH_SUBMIT,
    PATCH_SYNC,
    PATCH_TAG,
)
from sase.project_display_names import humanize_cl_name

from .proc_actions import TrackedProcCompletion

_PATCH_OPERATIONS: dict[str, str] = {
    "accept": PATCH_ACCEPT,
    "archive": PATCH_ARCHIVE,
    "mail": PATCH_MAIL,
    "rebase": PATCH_REBASE,
    "restore": PATCH_RESTORE,
    "revert": PATCH_REVERT,
    "rewind": PATCH_REWIND,
    "reword": PATCH_REWORD,
    "status": PATCH_STATUS,
    "submit": PATCH_SUBMIT,
    "sync": PATCH_SYNC,
    "tag": PATCH_TAG,
}


def submit_patch_operation(
    app: Any,
    *,
    verb: str,
    name: str,
    project_file: str,
    extra_argv: Sequence[str] = (),
    payload: Mapping[str, Any] | None = None,
    fingerprint_ids: Mapping[str, Any] | None = None,
    workspace_num: int | None = None,
    workspace_workflow: str | None = None,
    on_complete: Callable[[TrackedProcCompletion[Any]], None] | None = None,
    display_name: str | None = None,
    proc_type: str | None = None,
) -> bool:
    """Submit one focused ``sase patch`` operation through the durable adapter."""
    operation = _PATCH_OPERATIONS[verb]
    request_payload = dict(payload or {})
    request_payload.setdefault("name", name)
    request_payload.setdefault("project_file", project_file)
    argv = sase_command_argv("patch", verb, name, *extra_argv, "-p", project_file)
    keys = (patch_concurrency_key(project_file, name),)
    claim = None
    if workspace_num is not None:
        claim = workspace_claim_policy(
            project_file=project_file,
            workspace_num=workspace_num,
            workflow=workspace_workflow or verb,
            cl_name=name,
        )
        request_payload.setdefault("workspace_num", workspace_num)
    submitted = app._submit_durable_proc(
        argv,
        operation=operation,
        request=request_payload,
        request_fingerprint=operation_fingerprint(
            operation, fingerprint_ids or request_payload
        ),
        concurrency_keys=keys,
        proc_type=proc_type or verb,
        display_name=display_name or f"{verb} {humanize_cl_name(name)}",
        cl_name=name,
        project_file=project_file,
        workspace_claim=claim,
        on_complete=on_complete,
    )
    return submitted is not None


def claim_patch_workspace(
    project_file: str,
    name: str,
    workflow: str,
    project_basename: str,
) -> tuple[int, str] | tuple[None, str]:
    """Claim a workspace for a durable Patch mutation.

    Returns ``(workspace_num, workspace_dir)`` or ``(None, error)``.
    """
    import os

    from sase.running_field import (
        claim_workspace,
        get_first_available_axe_workspace,
        get_workspace_directory_for_num,
    )

    workspace_num = get_first_available_axe_workspace(project_file)
    try:
        workspace_dir, _ = get_workspace_directory_for_num(
            workspace_num, project_basename
        )
    except RuntimeError as exc:
        return None, str(exc)
    claimed = claim_workspace(project_file, workspace_num, workflow, os.getpid(), name)
    if not claimed.success:
        return None, claimed.error or "failed to claim workspace"
    return workspace_num, workspace_dir


__all__ = ["claim_patch_workspace", "submit_patch_operation"]
