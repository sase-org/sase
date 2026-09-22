"""Argument parser definitions for the ``sase service`` command."""

from __future__ import annotations

import argparse


def register_service_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register service-host lifecycle and service-proc commands."""
    service_parser = subparsers.add_parser(
        "service",
        help="Manage the per-machine SASE service host",
        description=(
            "Manage the per-machine SASE service host. Bare `sase service` "
            "is harmless and shows `sase service status`; use `sase service run` "
            "only when you intentionally want the host in the foreground."
        ),
    )
    service_parser.set_defaults(service_subcommand="status")
    service_sub = service_parser.add_subparsers(
        dest="service_subcommand",
        help="Service subcommands",
        metavar="{init,logs,proc,restart,run,start,status,stop,uninstall}",
    )

    init_parser = service_sub.add_parser(
        "init",
        help="Install or check the native service-host unit",
    )
    _add_check_diff_force_yes(
        init_parser, include_force=True, include_allow_agent_env=True
    )

    logs_parser = service_sub.add_parser(
        "logs",
        help="Show the detached service-host log",
    )
    logs_parser.add_argument(
        "-n",
        "--lines",
        type=int,
        default=200,
        metavar="N",
        help="Log lines to show (default: 200)",
    )

    _add_service_proc_parser(service_sub)

    restart_parser = service_sub.add_parser(
        "restart",
        help="Restart the detached service host",
    )
    _add_json_flag(restart_parser)

    service_sub.add_parser(
        "run",
        help="Run the service host in the foreground",
        description=(
            "Run the service host in the foreground. This command owns the host "
            "lock for its entire lifetime, supervises configured daemon service "
            "procs as direct children, and exits on SIGTERM, SIGINT, or Ctrl-C."
        ),
    )

    start_parser = service_sub.add_parser(
        "start",
        help="Start the service host detached",
    )
    _add_json_flag(start_parser)

    status_parser = service_sub.add_parser(
        "status",
        help="Show service host and proc status",
    )
    _add_json_flag(status_parser)

    stop_parser = service_sub.add_parser(
        "stop",
        help="Stop the running service host",
    )
    _add_json_flag(stop_parser)

    uninstall_parser = service_sub.add_parser(
        "uninstall",
        help="Unload and remove the native service-host unit",
    )
    _add_check_diff_force_yes(
        uninstall_parser,
        include_force=True,
        force_help=(
            "Allow uninstallation for a non-default SASE_HOME using a home-scoped "
            "unit identity"
        ),
    )


def _add_service_proc_parser(service_sub: argparse._SubParsersAction) -> None:
    proc_parser = service_sub.add_parser(
        "proc",
        help="Control configured service procs; bare `proc` defaults to `proc list`",
        description=(
            "Control configured daemon service procs and launch transient oneshot "
            "service procs. Running `sase service proc` defaults to "
            "`sase service proc list`."
        ),
    )
    proc_sub = proc_parser.add_subparsers(
        dest="service_proc_subcommand",
        help="Service proc subcommands",
        metavar="{disable,enable,list,logs,restart,run,show,start,stop}",
    )

    disable_parser = proc_sub.add_parser(
        "disable",
        help="Disable a configured service proc on this machine",
    )
    disable_parser.add_argument("name", metavar="NAME")

    enable_parser = proc_sub.add_parser(
        "enable",
        help="Enable a configured service proc on this machine",
    )
    enable_parser.add_argument("name", metavar="NAME")

    list_parser = proc_sub.add_parser(
        "list",
        help="List configured service procs",
    )
    _add_json_flag(list_parser)

    logs_parser = proc_sub.add_parser(
        "logs",
        help="Show one service proc's bounded output log",
    )
    logs_parser.add_argument("name", metavar="NAME")
    logs_parser.add_argument(
        "-n",
        "--lines",
        type=int,
        default=200,
        metavar="N",
        help="Log lines to show (default: 200)",
    )

    restart_parser = proc_sub.add_parser(
        "restart",
        help="Ask the service host to restart a service proc",
    )
    restart_parser.add_argument("name", metavar="NAME")
    _add_proc_wait_options(restart_parser)

    run_parser = proc_sub.add_parser(
        "run",
        help="Run a transient oneshot under the durable proc service",
        description=(
            "Submit a transient oneshot service proc through the durable proc "
            "service. It is not named, is not added to daemon desired state, and "
            "the service host never replays it after restart. It runs outside "
            "the service host's process tree, records its exit code, and shows "
            "in the Services tab's oneshots section under a #1-#9 index (at "
            "most nine can be running at once; finished ones never count). "
            "The TUI's `!!` background commands use this same path. Everything "
            "after `--` is the command to run."
        ),
    )
    run_parser.add_argument(
        "-c",
        "--cwd",
        default=None,
        metavar="DIR",
        help="Working directory for the command (default: current directory)",
    )
    _add_json_flag(run_parser)
    run_parser.add_argument(
        "-l",
        "--label",
        default=None,
        metavar="TEXT",
        help="Human-facing proc label (default: derived from command)",
    )
    run_parser.add_argument(
        "-p",
        "--project",
        default=None,
        metavar="NAME",
        help="Project to attribute the proc to",
    )
    run_parser.add_argument(
        "-w",
        "--workspace",
        type=int,
        default=None,
        metavar="N",
        help="Workspace number to attribute the proc to",
    )
    run_parser.add_argument(
        "proc_command",
        nargs=argparse.REMAINDER,
        metavar="-- COMMAND ...",
        help="Command to run, introduced by --",
    )

    show_parser = proc_sub.add_parser(
        "show",
        help="Show one configured service proc",
    )
    show_parser.add_argument("name", metavar="NAME")
    _add_json_flag(show_parser)

    start_parser = proc_sub.add_parser(
        "start",
        help="Ask the service host to start a service proc",
    )
    start_parser.add_argument("name", metavar="NAME")
    _add_proc_wait_options(start_parser)

    stop_parser = proc_sub.add_parser(
        "stop",
        help="Stop a service proc until the next boot",
    )
    stop_parser.add_argument("name", metavar="NAME")


def _add_proc_wait_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-n",
        "--no-wait",
        action="store_true",
        help="Return as soon as the request is recorded",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="How long to wait for the host to confirm (default: derived from the proc's stop timeout)",
    )


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )


def _add_check_diff_force_yes(
    parser: argparse.ArgumentParser,
    *,
    include_force: bool,
    force_help: str | None = None,
    include_allow_agent_env: bool = False,
) -> None:
    if include_allow_agent_env:
        parser.add_argument(
            "-a",
            "--allow-agent-env",
            action="store_true",
            help=(
                "Capture this shell's environment even from an agent shell "
                "or ephemeral workspace"
            ),
        )
    parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="Report platform-unit drift without writing files or changing the native manager",
    )
    parser.add_argument(
        "-d",
        "--diff",
        action="store_true",
        help="Show desired native-unit and redacted environment diffs without writing",
    )
    if include_force:
        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            help=force_help
            or (
                "Allow installation for a non-default SASE_HOME using a "
                "home-scoped unit identity"
            ),
        )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Apply the planned native-manager changes",
    )


__all__ = ["register_service_parser"]
