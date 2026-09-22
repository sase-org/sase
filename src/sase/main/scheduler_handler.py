"""Handlers for the canonical ``sase scheduler`` command."""

from __future__ import annotations

import argparse
import os
import sys
from typing import NoReturn

from sase.service.actions import ServiceProcActionError
from sase.service.config import ServiceConfigError


def handle_scheduler_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch scheduler commands through the SASE service host.

    ``run`` is the exception: it execs the foreground orchestrator that the
    service host itself runs for the ``scheduler`` service proc.
    """
    subcommand = getattr(args, "scheduler_subcommand", None) or "status"
    if subcommand == "run":
        sys.exit(_run_foreground_scheduler(args))

    try:
        code = _handle_service_scheduler(subcommand, args)
    except (ServiceConfigError, ServiceProcActionError) as exc:
        print(str(exc), file=sys.stderr)
        code = 2
    sys.exit(code)


def _run_foreground_scheduler(args: argparse.Namespace) -> int:
    """Run the existing AXE orchestrator in the foreground."""
    from sase.ace.query import QueryParseError
    from sase.axe.config import AxeConfigError
    from sase.axe.orchestrator import Orchestrator
    from sase.main.axe_handler import load_axe_config_with_overrides

    os.chdir(os.path.expanduser("~"))
    try:
        config = load_axe_config_with_overrides(args)
        orchestrator = Orchestrator(config)
    except AxeConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except QueryParseError as exc:
        print(f"Error: Invalid query: {exc}", file=sys.stderr)
        return 1
    return 0 if orchestrator.run() else 1


def _handle_service_scheduler(subcommand: str, args: argparse.Namespace) -> int:
    from sase.main.service_handler import (
        handle_service_proc_restart,
        handle_service_proc_show,
        handle_service_proc_start,
    )
    from sase.service.actions import stop_service_proc

    if subcommand == "start":
        args.name = "scheduler"
        return handle_service_proc_start(args)
    if subcommand == "status":
        args.name = "scheduler"
        return handle_service_proc_show(args)
    if subcommand == "stop":
        outcome = stop_service_proc("scheduler", actor="cli", reason="scheduler stop")
        print(outcome.message)
        return 0
    if subcommand == "restart":
        args.name = "scheduler"
        return handle_service_proc_restart(args)
    print("Usage: sase scheduler {restart,run,start,status,stop}", file=sys.stderr)
    return 2


__all__ = ["handle_scheduler_command"]
