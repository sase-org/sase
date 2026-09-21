"""Handler for the 'sase axe' command."""

from __future__ import annotations

import argparse
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.axe.config import AxeConfig


def handle_axe_command(args: argparse.Namespace) -> None:
    """Handle the 'sase axe' command."""
    from sase.feature_flags import install_process_feature_flags

    install_process_feature_flags()

    # Wire --vcs-provider to env var for downstream resolution
    vcs_provider = getattr(args, "vcs_provider", None)
    if vcs_provider is not None:
        os.environ["SASE_VCS_PROVIDER"] = vcs_provider

    axe_sub = getattr(args, "axe_subcommand", None)

    if axe_sub == "bgcmd-launch":
        _handle_bgcmd_launch(args)
    elif axe_sub in {"chop", "job"}:
        _handle_job(args)
    elif axe_sub in {"lumberjack", "routine"}:
        _handle_routine(args)
    elif axe_sub == "maintenance":
        _handle_maintenance(args)
    elif axe_sub in {"restart", "start", "status", "stop"}:
        _handle_scheduler_alias(args, axe_sub)
    else:
        print("Usage: sase axe {job,maintenance,restart,routine,start,status,stop}")
        sys.exit(1)


def _handle_scheduler_alias(args: argparse.Namespace, axe_sub: str) -> None:
    """Delegate axe lifecycle verbs to ``sase scheduler``."""
    from sase.main.scheduler_handler import handle_scheduler_command

    args.scheduler_subcommand = axe_sub
    handle_scheduler_command(args)


def _handle_bgcmd_launch(args: argparse.Namespace) -> None:
    """Handle the internal durable ``sase axe bgcmd-launch`` command."""
    from sase.axe.bgcmd_operations import run_bgcmd_launch
    from sase.ops.cli import load_request
    from sase.ops.commands.common import run_and_finish
    from sase.ops.names import AXE_BGCMD

    def _body() -> tuple[bool, str, dict[str, object]]:
        request = load_request(AXE_BGCMD, args, required=True)
        command = request.payload.get("command")
        workspace_dir = request.payload.get("workspace_dir")
        cl_name = request.payload.get("cl_name")
        if not isinstance(command, str) or not command:
            return False, "bgcmd request payload must include command", {}
        if not isinstance(workspace_dir, str) or not workspace_dir:
            return False, "bgcmd request payload must include workspace_dir", {}
        if cl_name is not None and not isinstance(cl_name, str):
            return False, "bgcmd request payload cl_name must be a string or null", {}
        success, message, payload = run_bgcmd_launch(
            slot=int(args.slot),
            command=command,
            project=str(args.project),
            workspace_num=int(args.workspace_num),
            workspace_dir=workspace_dir,
            cl_name=cl_name,
        )
        return success, message, dict(payload)

    sys.exit(run_and_finish(operation=AXE_BGCMD, body=_body, args=args))


def _handle_job(args: argparse.Namespace) -> None:
    """Handle ``sase axe job`` and hidden legacy ``chop`` subcommands."""
    from sase.axe.cli import (
        handle_axe_chop_doctor,
        handle_axe_chop_list,
        handle_axe_chop_run,
    )

    chop_sub = getattr(args, "axe_chop_subcommand", None)
    if chop_sub == "doctor":
        handle_axe_chop_doctor(args)
    elif chop_sub == "list":
        handle_axe_chop_list(args)
    elif chop_sub == "run":
        handle_axe_chop_run(args)
    else:
        print("Usage: sase axe job {doctor,list,run}")
        sys.exit(1)


def _handle_routine(args: argparse.Namespace) -> None:
    """Handle ``sase axe routine`` and hidden legacy ``lumberjack`` subcommands."""
    from sase.axe.cli import (
        handle_axe_lumberjack_list,
        handle_axe_lumberjack_run,
        handle_axe_lumberjack_status,
    )

    lumberjack_sub = getattr(args, "axe_lumberjack_subcommand", None)
    if lumberjack_sub == "list":
        handle_axe_lumberjack_list(args)
    elif lumberjack_sub == "run":
        handle_axe_lumberjack_run(args)
    elif lumberjack_sub == "status":
        handle_axe_lumberjack_status(args)
    else:
        print("Usage: sase axe routine {list,run,status}")
        sys.exit(1)


def _handle_maintenance(args: argparse.Namespace) -> None:
    """Handle 'sase axe maintenance' subcommands."""
    from sase.axe.maintenance import (
        clear_maintenance,
        read_maintenance,
        start_maintenance,
    )

    maintenance_sub = getattr(args, "axe_maintenance_subcommand", None)
    if maintenance_sub == "enter":
        started_marker = start_maintenance(str(args.reason))
        print(
            "Axe maintenance mode enabled "
            f"(reason: {started_marker['reason']}, pid: {started_marker['pid']})"
        )
        sys.exit(0)
    if maintenance_sub == "exit":
        if clear_maintenance():
            print("Axe maintenance mode disabled")
        else:
            print("Axe maintenance mode was not active")
        sys.exit(0)
    if maintenance_sub == "status":
        active_marker = read_maintenance()
        if active_marker is None:
            print("Axe maintenance mode is not active")
            sys.exit(1)
        print(
            "Axe maintenance mode is active "
            f"(reason: {active_marker['reason']}, "
            f"pid: {active_marker['pid']}, "
            f"started_at: {active_marker['started_at']})"
        )
        sys.exit(0)

    print("Usage: sase axe maintenance {enter,exit,status}")
    sys.exit(1)


def load_axe_config_with_overrides(args: argparse.Namespace) -> AxeConfig:
    """Load the effective axe config with CLI runner/query/timeout overrides applied."""
    from dataclasses import replace

    from sase.axe.config import load_axe_config

    config = load_axe_config()
    max_hook_runners = (
        args.max_hook_runners
        if getattr(args, "max_hook_runners", None) is not None
        else config.max_hook_runners
    )
    max_agent_runners = (
        args.max_agent_runners
        if getattr(args, "max_agent_runners", None) is not None
        else config.max_agent_runners
    )
    zombie_timeout = (
        args.zombie_timeout
        if getattr(args, "zombie_timeout", None) is not None
        else config.zombie_timeout_seconds
    )
    query = getattr(args, "query", "") or config.query

    return replace(
        config,
        max_hook_runners=max_hook_runners,
        max_agent_runners=max_agent_runners,
        zombie_timeout_seconds=zombie_timeout,
        query=query,
    )


__all__ = ["handle_axe_command", "load_axe_config_with_overrides"]
