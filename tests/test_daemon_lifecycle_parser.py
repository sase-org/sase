"""Parser tests for daemon lifecycle commands."""

from __future__ import annotations

from sase.main.parser import create_parser


def test_parser_accepts_daemon_start_flags() -> None:
    args = create_parser().parse_args(
        [
            "daemon",
            "start",
            "-H",
            "/tmp/sase",
            "--run-root",
            "/tmp/sase/run/host",
            "--socket-path",
            "/tmp/sase.sock",
            "--foreground",
            "--tokio-console",
            "--disable-mobile-http",
            "-b",
            "127.0.0.1:7630",
            "-L",
            "-c",
            "sase_gateway --trace",
            "-T",
            "1",
        ]
    )

    assert args.command == "daemon"
    assert args.daemon_subcommand == "start"
    assert args.sase_home == "/tmp/sase"
    assert args.run_root == "/tmp/sase/run/host"
    assert args.socket_path == "/tmp/sase.sock"
    assert args.foreground is True
    assert args.tokio_console is True
    assert args.disable_mobile_http is True
    assert args.bind_address == "127.0.0.1:7630"
    assert args.allow_non_loopback is True
    assert args.daemon_command == "sase_gateway --trace"
    assert args.startup_timeout == 1


def test_parser_accepts_projection_maintenance_commands() -> None:
    checkpoint = create_parser().parse_args(
        ["daemon", "checkpoint", "--mode", "truncate", "-T", "2", "--json"]
    )
    assert checkpoint.daemon_subcommand == "checkpoint"
    assert checkpoint.mode == "truncate"
    assert checkpoint.checkpoint_timeout == 2
    assert checkpoint.json_output is True

    backup = create_parser().parse_args(
        ["daemon", "backup", "--path", "manual.sqlite", "-T", "3"]
    )
    assert backup.daemon_subcommand == "backup"
    assert backup.backup_path == "manual.sqlite"
    assert backup.backup_timeout == 3

    listing = create_parser().parse_args(
        ["daemon", "list-backups", "--limit", "5", "-T", "4"]
    )
    assert listing.daemon_subcommand == "list-backups"
    assert listing.limit == 5
    assert listing.list_backups_timeout == 4

    restore = create_parser().parse_args(
        [
            "daemon",
            "restore",
            "/tmp/run/backups/manual.sqlite",
            "--live-recovery",
            "--allow-host-mismatch",
            "-T",
            "6",
        ]
    )
    assert restore.daemon_subcommand == "restore"
    assert restore.path == "/tmp/run/backups/manual.sqlite"
    assert restore.live_recovery is True
    assert restore.allow_host_mismatch is True
    assert restore.restore_timeout == 6


def test_parser_accepts_doctor_repair_stale_lock() -> None:
    args = create_parser().parse_args(["daemon", "doctor", "--repair-stale-lock"])

    assert args.daemon_subcommand == "doctor"
    assert args.repair_stale_lock is True


def test_parser_accepts_daemon_rollout_diagnostics() -> None:
    args = create_parser().parse_args(
        [
            "daemon",
            "rollout",
            "--no-daemon",
            "--benchmark-report",
            "/tmp/perf.json",
            "--json",
        ]
    )

    assert args.daemon_subcommand == "rollout"
    assert args.no_daemon is True
    assert args.benchmark_report == "/tmp/perf.json"
    assert args.json_output is True


def test_parser_accepts_daemon_scheduler_recovery_commands() -> None:
    args = create_parser().parse_args(
        [
            "daemon",
            "scheduler",
            "cancel",
            "--project",
            "sase",
            "--batch",
            "batch-a",
            "--slot",
            "slot-a",
            "--reason",
            "operator_recovery",
            "--json",
        ]
    )

    assert args.daemon_subcommand == "scheduler"
    assert args.daemon_scheduler_subcommand == "cancel"
    assert args.project_id == "sase"
    assert args.batch_id == "batch-a"
    assert args.slot_id == "slot-a"
    assert args.json_output is True
