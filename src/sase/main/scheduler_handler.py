"""Handlers for the canonical ``sase scheduler`` command."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import NoReturn

from sase.feature_flags import FeatureFlag, current_flags
from sase.service.actions import ServiceProcActionError
from sase.service.config import ServiceConfigError


def handle_scheduler_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch scheduler commands in either legacy or service-host mode."""
    subcommand = getattr(args, "scheduler_subcommand", None) or "status"
    if subcommand == "run":
        sys.exit(_run_foreground_scheduler(args))

    try:
        if current_flags().enabled(FeatureFlag.service_host):
            code = _handle_service_scheduler(subcommand, args)
        else:
            code = _handle_legacy_scheduler(subcommand, args)
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
    from sase.main.service_handler import handle_service_proc_show
    from sase.service.actions import (
        restart_service_proc,
        start_service_proc,
        stop_service_proc,
    )

    if subcommand == "start":
        outcome = start_service_proc("scheduler", actor="cli")
        print(outcome.message)
        return 0
    if subcommand == "status":
        args.name = "scheduler"
        return handle_service_proc_show(args)
    if subcommand == "stop":
        outcome = stop_service_proc("scheduler", actor="cli", reason="scheduler stop")
        print(outcome.message)
        return 0
    if subcommand == "restart":
        outcome = restart_service_proc(
            "scheduler",
            actor="cli",
            reason="scheduler restart",
            delay=0.0,
        )
        print(outcome.message)
        return 0
    print("Usage: sase scheduler {restart,run,start,status,stop}", file=sys.stderr)
    return 2


def _handle_legacy_scheduler(subcommand: str, args: argparse.Namespace) -> int:
    if subcommand == "start":
        return _legacy_start(args)
    if subcommand == "status":
        return _legacy_status(args)
    if subcommand == "stop":
        return _legacy_stop(args)
    if subcommand == "restart":
        return _legacy_restart(args)
    print("Usage: sase scheduler {restart,run,start,status,stop}", file=sys.stderr)
    return 2


def _legacy_start(args: argparse.Namespace) -> int:
    from sase.axe.config import AxeConfigError
    from sase.axe.process import start_axe_daemon_result
    from sase.main.axe_handler import load_axe_config_with_overrides

    try:
        config = load_axe_config_with_overrides(args)
    except AxeConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    result = start_axe_daemon_result(config)
    print(result.message)
    return 0 if result.succeeded else 1


def _legacy_status(args: argparse.Namespace) -> int:
    from sase.axe.status_collector import collect_axe_status_snapshot
    from sase.axe.status_render import render_axe_status_human, render_axe_status_json

    snapshot = collect_axe_status_snapshot()
    if bool(getattr(args, "json", False)):
        render_axe_status_json(snapshot)
    else:
        render_axe_status_human(snapshot)
    return snapshot.exit_code


def _legacy_stop(args: argparse.Namespace) -> int:
    from sase.axe.process import stop_axe_daemon_result

    result = stop_axe_daemon_result(force=bool(getattr(args, "force", False)))
    if getattr(args, "json", False):
        json.dump(result.__dict__, sys.stdout, indent=2, sort_keys=True, default=str)
        sys.stdout.write("\n")
    else:
        print(result.summary())
    return 0 if result.error is None and not result.failed_pids else 1


def _legacy_restart(args: argparse.Namespace) -> int:
    from sase.axe.config import AxeConfigError
    from sase.axe.process import restart_axe_daemon_result
    from sase.axe.restart_render import render_restart_json
    from sase.main.axe_handler import load_axe_config_with_overrides

    try:
        config = load_axe_config_with_overrides(args)
    except AxeConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    result = restart_axe_daemon_result(
        config,
        verification_timeout=float(getattr(args, "verify_timeout", 15.0)),
    )
    if bool(getattr(args, "json", False)):
        render_restart_json(result, 0.0)
    else:
        print(result.message)
    return 0 if result.succeeded and result.verified else 1


__all__ = ["handle_scheduler_command"]
