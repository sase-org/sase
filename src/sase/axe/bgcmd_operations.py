"""Durable AXE background-command launch operation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.ace.tui.bgcmd import clear_slot_pending, start_background_command
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
    """Checkout an optional Patch and launch a background command in *slot*."""
    try:
        if cl_name is not None:
            clean_ok, clean_err = run_sase_hg_clean(workspace_dir, f"{cl_name}-bgcmd")
            if not clean_ok:
                print(f"Warning: sase_hg_clean failed: {clean_err}")

            provider = get_vcs_provider(workspace_dir)
            resolved = provider.resolve_revision(cl_name, project, workspace_dir)
            checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
            if not checkout_ok:
                return (
                    False,
                    f"checkout failed: {checkout_err}",
                    {"slot": slot, "project": project, "workspace_num": workspace_num},
                )

        pid = start_background_command(
            slot=slot,
            command=command,
            project=project,
            workspace_num=workspace_num,
            workspace_dir=workspace_dir,
        )
        if pid is None:
            return (
                False,
                "Failed to start background command",
                {"slot": slot, "project": project, "workspace_num": workspace_num},
            )

        cmd_notify = command[:30] + "..." if len(command) > 30 else command
        return (
            True,
            f"Started bgcmd in slot {slot}: {cmd_notify}",
            {
                "cl_name": cl_name,
                "pid": pid,
                "project": project,
                "slot": slot,
                "workspace_num": workspace_num,
            },
        )
    finally:
        clear_slot_pending(slot)


__all__ = ["run_bgcmd_launch"]
