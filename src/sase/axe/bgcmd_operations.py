"""Durable AXE background-command launch operation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.procs import ProcSubmitError
from sase.procs.oneshot import oneshot_shell_argv, submit_oneshot
from sase.vcs_provider import get_vcs_provider
from sase.workflows.commit_utils import run_sase_hg_clean


def run_bgcmd_launch(
    *,
    slot: int,
    command: str,
    project: str,
    workspace_num: int,
    workspace_dir: str,
    cl_name: str | None,
) -> tuple[bool, str, Mapping[str, Any]]:
    """Checkout an optional Patch, then submit *command* as oneshot ``#slot``.

    The command runs as its own durable oneshot service proc, detached from
    this launch operation, so it outlives this process and records its own
    exit code.
    """
    failure_payload = {
        "slot": slot,
        "project": project,
        "workspace_num": workspace_num,
    }
    if cl_name is not None:
        clean_ok, clean_err = run_sase_hg_clean(workspace_dir, f"{cl_name}-bgcmd")
        if not clean_ok:
            print(f"Warning: sase_hg_clean failed: {clean_err}")

        provider = get_vcs_provider(workspace_dir)
        resolved = provider.resolve_revision(cl_name, project, workspace_dir)
        checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
        if not checkout_ok:
            return False, f"checkout failed: {checkout_err}", failure_payload

    try:
        proc = submit_oneshot(
            oneshot_shell_argv(command),
            label=command,
            cwd=workspace_dir,
            project=project,
            workspace_num=workspace_num,
            cl_name=cl_name,
            slot=slot,
        )
    except ProcSubmitError as exc:
        return (
            False,
            f"Failed to start background command: {exc}",
            failure_payload,
        )

    cmd_notify = command[:30] + "..." if len(command) > 30 else command
    return (
        True,
        f"Started oneshot #{slot}: {cmd_notify}",
        {
            "cl_name": cl_name,
            "pid": proc.pid,
            "proc_id": proc.proc_id,
            "project": project,
            "slot": slot,
            "workspace_num": workspace_num,
        },
    )


__all__ = ["run_bgcmd_launch"]
