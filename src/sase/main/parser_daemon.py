"""Argument parser definition for the ``sase daemon`` CLI subcommand."""

from __future__ import annotations

import argparse

HELP_FORMATTER = argparse.RawDescriptionHelpFormatter


def register_daemon_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase daemon`` subcommand parser."""
    daemon_parser = subparsers.add_parser(
        "daemon",
        help="Manage local daemon runtime, diagnostics, and projection recovery",
        description=(
            "Manage the local SASE daemon.\n\n"
            "Common recovery flow:\n"
            "  sase daemon status\n"
            "  sase daemon doctor\n"
            "  sase daemon verify --surface all\n"
            "  sase daemon diff --surface all\n"
            "  sase daemon rebuild --surface all\n"
            "  sase daemon backup\n"
            "  sase daemon restore <backup.sqlite>\n\n"
            "Source stores remain authoritative. Daemon projections, sockets, "
            "locks, logs, WAL/SHM files, and backups are host-local runtime "
            "state under run_root."
        ),
        epilog=(
            "Use --no-daemon on daemon-capable read commands, or "
            "SASE_NO_DAEMON=1, to force direct source-store reads."
        ),
        formatter_class=HELP_FORMATTER,
    )
    daemon_subparsers = daemon_parser.add_subparsers(
        dest="daemon_subcommand", help="Daemon subcommands"
    )

    daemon_subparsers.add_parser(
        "provider-host",
        help=argparse.SUPPRESS,
    )

    scheduler_bridge_parser = daemon_subparsers.add_parser(
        "scheduler-bridge",
        help=argparse.SUPPRESS,
    )
    scheduler_bridge_subparsers = scheduler_bridge_parser.add_subparsers(
        dest="daemon_scheduler_bridge_subcommand",
    )
    scheduler_bridge_subparsers.add_parser(
        "prepare-launch-slot",
        help=argparse.SUPPRESS,
    )
    scheduler_bridge_subparsers.add_parser(
        "execute-launch-slot",
        help=argparse.SUPPRESS,
    )
    scheduler_bridge_subparsers.add_parser(
        "cancel-launch-slot",
        help=argparse.SUPPRESS,
    )
    scheduler_bridge_subparsers.add_parser(
        "prepare-axe-task",
        help=argparse.SUPPRESS,
    )
    scheduler_bridge_subparsers.add_parser(
        "execute-axe-task",
        help=argparse.SUPPRESS,
    )

    start_parser = daemon_subparsers.add_parser(
        "start",
        help="Start the local daemon",
    )
    _add_runtime_options(start_parser)
    start_parser.add_argument(
        "--foreground",
        action="store_true",
        help="Run the daemon in the foreground",
    )
    start_parser.add_argument(
        "--tokio-console",
        action="store_true",
        help="Enable tokio-console support when the gateway was built with it",
    )
    start_parser.add_argument(
        "--disable-mobile-http",
        action="store_true",
        help="Disable the mobile HTTP API inside daemon mode",
    )
    start_parser.add_argument(
        "-b",
        "--bind",
        dest="bind_address",
        help="Mobile HTTP host:port bind passed through to sase_gateway daemon",
    )
    start_parser.add_argument(
        "-L",
        "--allow-non-loopback",
        action="store_true",
        help="Allow explicit non-loopback mobile HTTP binds",
    )
    start_parser.add_argument(
        "-A",
        "--agent-bridge-command",
        help=argparse.SUPPRESS,
    )
    start_parser.add_argument(
        "-J",
        "--helper-bridge-command",
        help=argparse.SUPPRESS,
    )
    start_parser.add_argument(
        "-c",
        "--command",
        dest="daemon_command",
        help="Gateway command override, parsed without a shell",
    )
    start_parser.add_argument(
        "-T",
        "--startup-timeout",
        type=float,
        help="Seconds to wait for background startup metadata",
    )

    stop_parser = daemon_subparsers.add_parser(
        "stop",
        help="Stop the local daemon",
    )
    _add_runtime_options(stop_parser)
    stop_parser.add_argument(
        "-T",
        "--timeout",
        type=float,
        dest="stop_timeout",
        help="Seconds to wait after sending the stop signal",
    )

    status_parser = daemon_subparsers.add_parser(
        "status",
        help="Show local daemon status",
    )
    _add_runtime_options(status_parser)
    status_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable status JSON",
    )

    scheduler_parser = daemon_subparsers.add_parser(
        "scheduler",
        help="Inspect and recover daemon scheduler batches",
    )
    _add_runtime_options(scheduler_parser)
    scheduler_subparsers = scheduler_parser.add_subparsers(
        dest="daemon_scheduler_subcommand",
        help="Scheduler subcommands",
    )
    scheduler_status_parser = scheduler_subparsers.add_parser(
        "status",
        help="Show a scheduler batch status",
    )
    scheduler_status_parser.add_argument(
        "--project",
        dest="project_id",
        required=True,
        help="Scheduler project id",
    )
    scheduler_status_parser.add_argument(
        "--batch",
        dest="batch_id",
        required=True,
        help="Scheduler batch id",
    )
    scheduler_status_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable scheduler status JSON",
    )
    scheduler_cancel_parser = scheduler_subparsers.add_parser(
        "cancel",
        help="Cancel stuck queued, starting, or running scheduler work",
    )
    scheduler_cancel_parser.add_argument(
        "--project",
        dest="project_id",
        required=True,
        help="Scheduler project id",
    )
    scheduler_cancel_parser.add_argument(
        "--batch",
        dest="batch_id",
        required=True,
        help="Scheduler batch id",
    )
    scheduler_cancel_parser.add_argument(
        "--slot",
        dest="slot_id",
        help="Specific scheduler slot id to cancel; omit to cancel the batch",
    )
    scheduler_cancel_parser.add_argument(
        "--reason",
        default="operator_recovery",
        help="Recovery reason recorded on scheduler events",
    )
    scheduler_cancel_parser.add_argument(
        "--idempotency-key",
        dest="idempotency_key",
        help="Stable idempotency key for retrying this recovery action",
    )
    scheduler_cancel_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable cancel result JSON",
    )

    doctor_parser = daemon_subparsers.add_parser(
        "doctor",
        help="Diagnose daemon health and print exact repair commands",
        description=(
            "Diagnose daemon lifecycle, storage layout, projection health, "
            "source-export conflicts, scheduler state, and mobile HTTP health.\n\n"
            "Start with:\n"
            "  sase daemon doctor\n"
            "  sase daemon doctor --json"
        ),
        formatter_class=HELP_FORMATTER,
    )
    _add_runtime_options(doctor_parser)
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable diagnostic JSON",
    )
    doctor_parser.add_argument(
        "--repair-stale-lock",
        action="store_true",
        help=(
            "Remove same-host stale daemon lock, metadata, and host-local socket "
            "runtime files after doctor confirms no live process owns the lock"
        ),
    )

    rebuild_parser = daemon_subparsers.add_parser(
        "rebuild",
        help="Rebuild runtime projections from authoritative source stores",
        description=(
            "Rebuild daemon projections from source stores through the live "
            "daemon. Source files, JSONL stores, artifacts, and repos are not "
            "deleted by rebuild.\n\n"
            "Use --reset-storage only for the explicit one-shot projection "
            "table reset/replay recovery path."
        ),
        formatter_class=HELP_FORMATTER,
    )
    _add_runtime_options(rebuild_parser)
    rebuild_parser.add_argument(
        "--surface",
        choices=[
            "changespecs",
            "notifications",
            "agents",
            "beads",
            "catalogs",
            "all",
        ],
        default="all",
        help="Projection surface to rebuild from source stores",
    )
    rebuild_parser.add_argument(
        "--project",
        dest="project_id",
        help="Project id to rebuild when supported by the selected surface",
    )
    rebuild_parser.add_argument(
        "--reset-storage",
        action="store_true",
        dest="storage_reset_only",
        help="Replay retained projection events after resetting projection tables",
    )
    rebuild_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable rebuild JSON",
    )
    rebuild_parser.add_argument(
        "-T",
        "--timeout",
        type=float,
        dest="rebuild_timeout",
        help="Seconds to wait for live-daemon rebuild RPC",
    )

    checkpoint_parser = daemon_subparsers.add_parser(
        "checkpoint",
        help="Checkpoint the host-local projection WAL",
    )
    _add_runtime_options(checkpoint_parser)
    checkpoint_parser.add_argument(
        "--mode",
        choices=["passive", "full", "restart", "truncate"],
        default="passive",
        help="SQLite WAL checkpoint mode",
    )
    checkpoint_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable checkpoint JSON",
    )
    checkpoint_parser.add_argument(
        "-T",
        "--timeout",
        type=float,
        dest="checkpoint_timeout",
        help="Seconds to wait for live-daemon checkpoint RPC",
    )

    backup_parser = daemon_subparsers.add_parser(
        "backup",
        help="Create a host-local projection backup snapshot",
        description=(
            "Create a projection-only backup snapshot under run_root/backups "
            "by default. Backups capture runtime projection state and do not "
            "copy source stores."
        ),
        formatter_class=HELP_FORMATTER,
    )
    _add_runtime_options(backup_parser)
    backup_parser.add_argument(
        "--path",
        dest="backup_path",
        help="Backup path under run_root/backups; default creates a timestamped .sqlite",
    )
    backup_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable backup JSON",
    )
    backup_parser.add_argument(
        "-T",
        "--timeout",
        type=float,
        dest="backup_timeout",
        help="Seconds to wait for live-daemon backup RPC",
    )

    list_backups_parser = daemon_subparsers.add_parser(
        "list-backups",
        help="List recent host-local projection backup snapshots",
    )
    _add_runtime_options(list_backups_parser)
    list_backups_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum backup records to return",
    )
    list_backups_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable backup list JSON",
    )
    list_backups_parser.add_argument(
        "-T",
        "--timeout",
        type=float,
        dest="list_backups_timeout",
        help="Seconds to wait for live-daemon backup-list RPC",
    )

    restore_parser = daemon_subparsers.add_parser(
        "restore",
        help="Restore a projection backup without touching source stores",
        description=(
            "Restore a projection backup into run_root/projections. Restore "
            "is projection-only: it does not edit source stores, JSONL files, "
            "ProjectSpec files, artifacts, or external repos."
        ),
        formatter_class=HELP_FORMATTER,
    )
    _add_runtime_options(restore_parser)
    restore_parser.add_argument(
        "path",
        help="Projection backup .sqlite path under run_root/backups",
    )
    restore_parser.add_argument(
        "--live-recovery",
        action="store_true",
        help="Allow guarded restore through a running daemon",
    )
    restore_parser.add_argument(
        "--allow-host-mismatch",
        action="store_true",
        help="Allow restoring a backup created by a different host",
    )
    restore_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable restore JSON",
    )
    restore_parser.add_argument(
        "-T",
        "--timeout",
        type=float,
        dest="restore_timeout",
        help="Seconds to wait for restore RPC",
    )

    verify_parser = daemon_subparsers.add_parser(
        "verify",
        help="Verify runtime projections against authoritative source stores",
    )
    _add_runtime_options(verify_parser)
    _add_indexing_selector_options(verify_parser)
    verify_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable verify JSON",
    )
    verify_parser.add_argument(
        "-T",
        "--timeout",
        type=float,
        dest="verify_timeout",
        help="Seconds to wait for live-daemon verify RPC",
    )

    diff_parser = daemon_subparsers.add_parser(
        "diff",
        help="Show bounded runtime projection differences",
    )
    _add_runtime_options(diff_parser)
    _add_indexing_selector_options(diff_parser)
    diff_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable diff JSON",
    )
    diff_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum diff records to return",
    )
    diff_parser.add_argument(
        "--cursor",
        help="Opaque diff cursor from a previous response",
    )
    diff_parser.add_argument(
        "-T",
        "--timeout",
        type=float,
        dest="diff_timeout",
        help="Seconds to wait for live-daemon diff RPC",
    )


def _add_runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-H",
        "--sase-home",
        help="SASE state root (default: SASE_HOME or ~/.sase)",
    )
    parser.add_argument(
        "--run-root",
        help="Host-local daemon runtime directory",
    )
    parser.add_argument(
        "--socket-path",
        help="Local daemon socket path",
    )


def _add_indexing_selector_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--surface",
        choices=[
            "changespecs",
            "notifications",
            "agents",
            "beads",
            "catalogs",
            "all",
        ],
        default="all",
        help="Projection surface to inspect",
    )
    parser.add_argument(
        "--project",
        dest="project_id",
        help="Project id to inspect when supported by the selected surface",
    )
