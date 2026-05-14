"""Tests for the SASE daemon Python lifecycle wrapper."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sase.integrations import daemon_lifecycle as lifecycle
from sase.integrations.daemon_lifecycle import (
    _DaemonLifecycleConfig,
    _DaemonLifecycleError,
    _prepare_daemon_launch,
)
from sase.main.parser import create_parser


def _args(**overrides: Any) -> argparse.Namespace:
    values = {
        "sase_home": None,
        "run_root": None,
        "socket_path": None,
        "foreground": False,
        "tokio_console": False,
        "disable_mobile_http": False,
        "bind_address": None,
        "allow_non_loopback": False,
        "agent_bridge_command": None,
        "helper_bridge_command": None,
        "daemon_command": None,
        "startup_timeout": None,
        "stop_timeout": None,
        "rebuild_timeout": None,
        "checkpoint_timeout": None,
        "backup_timeout": None,
        "list_backups_timeout": None,
        "restore_timeout": None,
        "verify_timeout": None,
        "diff_timeout": None,
        "backup_path": None,
        "path": None,
        "live_recovery": False,
        "allow_host_mismatch": False,
        "surface": "all",
        "project_id": None,
        "storage_reset_only": False,
        "limit": 100,
        "cursor": None,
        "json_output": False,
        "repair_stale_lock": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _metadata(pid: int, host: str, **overrides: Any) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "pid": pid,
        "hostname": host,
        "boot_session_hint": "boot",
        "executable_path": str(Path("/proc") / str(pid) / "exe"),
        "socket_path": "/tmp/sase-daemon.sock",
        "started_at": "2026-05-13T00:00:00Z",
        "sase_home": "/tmp/sase",
        "build_version": "test",
    }
    payload.update(overrides)
    return payload


def _write_metadata(run_root: Path, payload: dict[str, Any]) -> None:
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "daemon.lock.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


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


def test_prepare_daemon_launch_builds_safe_argv(tmp_path: Path) -> None:
    launch = _prepare_daemon_launch(
        _args(
            sase_home=str(tmp_path / "home"),
            run_root=str(tmp_path / "run"),
            socket_path=str(tmp_path / "daemon.sock"),
            foreground=True,
            tokio_console=True,
            disable_mobile_http=True,
            bind_address="127.0.0.1:7630",
            agent_bridge_command="sase --bridge",
            helper_bridge_command="sase-helper",
            startup_timeout=2,
        ),
        config=_DaemonLifecycleConfig(command=("sase_gateway",)),
    )

    assert launch.argv == [
        "sase_gateway",
        "daemon",
        "--sase-home",
        str(tmp_path / "home"),
        "--run-root",
        str(tmp_path / "run"),
        "--socket-path",
        str(tmp_path / "daemon.sock"),
        "--foreground",
        "--tokio-console",
        "--disable-mobile-http",
        "--bind",
        "127.0.0.1:7630",
        "--agent-bridge-command",
        "sase --bridge",
        "--helper-bridge-command",
        "sase-helper",
    ]
    assert launch.foreground is True
    assert launch.startup_timeout_seconds == 2


def test_prepare_daemon_launch_missing_binary_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lifecycle, "_resolve_gateway_command", lambda: ())
    with pytest.raises(_DaemonLifecycleError, match="sase_gateway binary not found"):
        _prepare_daemon_launch(_args(), config=_DaemonLifecycleConfig())


def test_python_path_contract_matches_rust_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = [
        (
            "workstation.local",
            "/tmp/sase-home/run/workstation.local",
            "/tmp/sase-home/run/workstation.local/sase-daemon.sock",
        ),
        (
            "  ",
            "/tmp/sase-home/run/sase-host",
            "/tmp/sase-home/run/sase-host/sase-daemon.sock",
        ),
        (
            "work station/01",
            "/tmp/sase-home/run/work-station-01",
            "/tmp/sase-home/run/work-station-01/sase-daemon.sock",
        ),
    ]
    for host, run_root, socket_path in cases:
        monkeypatch.setenv("HOSTNAME", host)
        paths = lifecycle._runtime_paths_from_args(
            _args(sase_home="/tmp/sase-home"),
            config=_DaemonLifecycleConfig(),
        )

        assert paths.run_root == Path(run_root)
        assert paths.socket_path == Path(socket_path)

    override_paths = lifecycle._runtime_paths_from_args(
        _args(sase_home="/tmp/sase-home", run_root="/tmp/sase-run"),
        config=_DaemonLifecycleConfig(),
    )
    assert override_paths.run_root == Path("/tmp/sase-run")
    assert override_paths.socket_path == Path("/tmp/sase-run/sase-daemon.sock")


def test_inspect_daemon_stopped(tmp_path: Path) -> None:
    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(tmp_path / "run"))
    )

    assert inspection.state == "stopped"
    assert "no ownership metadata" in inspection.message


def test_inspect_daemon_running_from_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(os.getpid(), "workstation.local"))

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )

    assert inspection.state == "running"
    assert inspection.metadata is not None
    assert inspection.metadata["pid"] == os.getpid()
    assert inspection.rpc is not None
    assert inspection.rpc["available"] is False


def test_inspect_daemon_stale_dead_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(4_294_967_000, "workstation.local"))

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )

    assert inspection.state == "stale"
    assert "not live" in inspection.message


def test_inspect_daemon_reports_missing_metadata_stale_lock(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / lifecycle.LOCK_FILENAME).write_text("", encoding="utf-8")

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )

    assert inspection.state == "stale"
    assert "without ownership metadata" in inspection.message


def test_inspect_daemon_reports_malformed_metadata_as_stale(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / lifecycle.LOCK_FILENAME).write_text("", encoding="utf-8")
    (run_root / lifecycle.LOCK_METADATA_FILENAME).write_text(
        "{not-json",
        encoding="utf-8",
    )

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )

    assert inspection.state == "stale"
    assert "failed to parse ownership metadata" in inspection.message


def test_inspect_daemon_live_pid_mismatched_executable_is_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(1234, "workstation.local"))
    monkeypatch.setattr(lifecycle, "_process_is_live", lambda _pid: True)
    monkeypatch.setattr(
        lifecycle,
        "_executable_matches_metadata",
        lambda _pid, _metadata: False,
    )

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )

    assert inspection.state == "conflict"
    assert "executable does not match" in inspection.message


def test_stop_refuses_mismatched_host_without_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "this-host")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(1234, "other-host"))
    signals: list[tuple[int, int]] = []

    with pytest.raises(_DaemonLifecycleError, match="refusing to stop"):
        lifecycle._run_daemon_stop(  # noqa: SLF001
            _args(sase_home=str(tmp_path / "home"), run_root=str(run_root)),
            kill=lambda pid, sig: signals.append((pid, sig)),
            sleep=lambda _seconds: None,
        )

    assert signals == []


def test_stop_signals_matching_live_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HOSTNAME", "this-host")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(1234, "this-host"))
    signals: list[tuple[int, int]] = []
    live_checks = iter([True, False])
    monkeypatch.setattr(
        lifecycle,
        "_process_is_live",
        lambda _pid: next(live_checks, False),
    )
    monkeypatch.setattr(
        lifecycle,
        "_executable_matches_metadata",
        lambda _pid, _metadata: True,
    )

    code = lifecycle._run_daemon_stop(  # noqa: SLF001
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root)),
        kill=lambda pid, sig: signals.append((pid, sig)),
        sleep=lambda _seconds: None,
    )

    assert code == 0
    assert signals == [(1234, lifecycle.signal.SIGTERM)]
    assert "Stopped SASE daemon pid 1234" in capsys.readouterr().out


def test_background_start_reports_metadata_without_rpc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HOSTNAME", "this-host")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(1234, "this-host"))
    monkeypatch.setattr(lifecycle, "_process_is_live", lambda _pid: True)

    class FakeProcess:
        def poll(self) -> int | None:
            return None

    popen_calls: list[dict[str, Any]] = []

    def fake_popen(argv: list[str], **kwargs: Any) -> FakeProcess:
        popen_calls.append({"argv": argv, **kwargs})
        return FakeProcess()

    code = lifecycle._run_daemon_start(  # noqa: SLF001
        _args(
            sase_home=str(tmp_path / "home"),
            run_root=str(run_root),
            daemon_command="sase_gateway",
            disable_mobile_http=True,
            startup_timeout=1,
        ),
        popen=fake_popen,
        sleep=lambda _seconds: None,
    )

    assert code == 0
    assert popen_calls[0]["argv"] == [
        "sase_gateway",
        "daemon",
        "--sase-home",
        str(tmp_path / "home"),
        "--run-root",
        str(run_root),
        "--disable-mobile-http",
    ]
    assert popen_calls[0]["start_new_session"] is True
    assert "RPC health is unavailable" in capsys.readouterr().out


def test_status_json_includes_log_path_and_metrics_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(os.getpid(), "workstation.local"))
    monkeypatch.setattr(
        lifecycle,
        "_try_health_rpc",
        lambda _socket: {
            "available": True,
            "health": {
                "details": {"metrics": {"endpoint": "http://127.0.0.1:7629/metrics"}}
            },
        },
    )

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )
    payload = lifecycle._inspection_to_dict(inspection)

    assert payload["log_path"] == str(run_root / "daemon.log")
    assert payload["projection_db_path"] == str(
        run_root / "projections" / "projection.sqlite"
    )
    assert payload["storage_layout"]["run_root"]["path_kind"] == "host_local_override"
    assert (
        str(run_root / "daemon.lock.json") in payload["storage_layout"]["runtime_files"]
    )
    assert payload["metrics_endpoint"] == "http://127.0.0.1:7629/metrics"


def test_doctor_reports_unsafe_storage_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    home = tmp_path / "home"
    run_root = home / "projects" / "demo" / "run"

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(home), run_root=str(run_root))
    )
    payload = lifecycle._doctor_payload(inspection)  # noqa: SLF001

    layout_check = [
        check
        for check in payload["doctor"]["checks"]
        if check["name"] == "storage_layout"
    ][0]
    assert layout_check["state"] == "error"
    assert "run_root_under_source_root" in layout_check["message"]
    assert payload["storage_layout"]["run_root"]["path_kind"] == "source_root"
    assert [action["id"] for action in payload["repair_actions"]] == ["move_run_root"]


def test_doctor_reports_stable_repair_actions_for_stale_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(4_294_967_000, "workstation.local"))

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )
    payload = lifecycle._doctor_payload(inspection)  # noqa: SLF001

    assert payload["repair_actions"] == payload["doctor"]["repair_actions"]
    remove_stale_lock = payload["repair_actions"][0]
    assert remove_stale_lock["id"] == "remove_stale_lock"
    assert remove_stale_lock["risk"] == "runtime_only"
    assert "--repair-stale-lock" in remove_stale_lock["command"]


def test_doctor_human_output_prints_exact_repair_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(4_294_967_000, "workstation.local"))

    code = lifecycle.handle_daemon_doctor(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "Repair actions:" in out
    assert "- remove_stale_lock: runtime_only" in out
    assert "Command: sase daemon doctor" in out
    assert "--repair-stale-lock" in out


def test_doctor_repair_stale_lock_removes_runtime_only_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    socket_path = run_root / "sase-daemon.sock"
    _write_metadata(run_root, _metadata(4_294_967_000, "workstation.local"))
    (run_root / lifecycle.LOCK_FILENAME).write_text("", encoding="utf-8")
    socket_path.write_text("stale socket", encoding="utf-8")

    payload = lifecycle._repair_stale_lock(  # noqa: SLF001
        _args(
            sase_home=str(tmp_path / "home"),
            run_root=str(run_root),
            socket_path=str(socket_path),
        )
    )

    assert payload["action"] == "remove_stale_lock"
    assert not (run_root / lifecycle.LOCK_FILENAME).exists()
    assert not (run_root / lifecycle.LOCK_METADATA_FILENAME).exists()
    assert not socket_path.exists()


def test_doctor_repair_stale_lock_refuses_host_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "this-host")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(4_294_967_000, "other-host"))

    with pytest.raises(_DaemonLifecycleError, match="refusing stale-lock repair"):
        lifecycle._repair_stale_lock(  # noqa: SLF001
            _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
        )


def test_parser_accepts_doctor_repair_stale_lock() -> None:
    args = create_parser().parse_args(["daemon", "doctor", "--repair-stale-lock"])

    assert args.daemon_subcommand == "doctor"
    assert args.repair_stale_lock is True


def test_doctor_distinguishes_degraded_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(os.getpid(), "workstation.local"))
    monkeypatch.setattr(
        lifecycle,
        "_try_health_rpc",
        lambda _socket: {
            "available": True,
            "health": {
                "status": "degraded",
                "details": {
                    "projection_db": {
                        "state": "degraded",
                        "schema_initialized": True,
                        "migrations_applied": True,
                        "repair_needed": True,
                        "gap_count": 1,
                        "recovery_issue_count": 0,
                        "message": "projection replay needs repair",
                    }
                },
            },
        },
    )

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )
    payload = lifecycle._doctor_payload(inspection)  # noqa: SLF001

    assert payload["doctor"]["state"] == "degraded"
    projection = [
        check
        for check in payload["doctor"]["checks"]
        if check["name"] == "projection_db"
    ][0]
    assert projection["state"] == "degraded"
    assert projection["message"] == "projection replay needs repair"


def test_doctor_reports_source_export_conflicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(os.getpid(), "workstation.local"))
    monkeypatch.setattr(
        lifecycle,
        "_try_health_rpc",
        lambda _socket: {
            "available": True,
            "health": {
                "status": "degraded",
                "details": {
                    "projection_db": {
                        "state": "degraded",
                        "schema_initialized": True,
                        "migrations_applied": True,
                        "repair_needed": True,
                        "gap_count": 0,
                        "recovery_issue_count": 1,
                        "source_exports": {
                            "state": "degraded",
                            "message": "1 source export(s) still need repair",
                            "pending": 0,
                            "failed": 0,
                            "conflict": 1,
                        },
                    }
                },
            },
        },
    )

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )
    payload = lifecycle._doctor_payload(inspection)  # noqa: SLF001

    source_exports = [
        check
        for check in payload["doctor"]["checks"]
        if check["name"] == "source_exports"
    ][0]
    assert source_exports["state"] == "degraded"
    assert source_exports["message"] == "1 source export(s) still need repair"


def test_doctor_reports_scheduler_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(os.getpid(), "workstation.local"))
    monkeypatch.setattr(
        lifecycle,
        "_try_health_rpc",
        lambda _socket: {
            "available": True,
            "health": {
                "status": "degraded",
                "details": {
                    "scheduler": {
                        "state": "degraded",
                        "queue_depth": 3,
                        "running_tasks": 2,
                        "starting_tasks": 1,
                        "blocked_tasks": 0,
                        "stale_starts": 1,
                        "host_bridge": {"available": True},
                        "projection_lag": {"pending_events": 0},
                    }
                },
            },
        },
    )

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )
    payload = lifecycle._doctor_payload(inspection)  # noqa: SLF001

    scheduler = [
        check for check in payload["doctor"]["checks"] if check["name"] == "scheduler"
    ][0]
    assert scheduler["state"] == "degraded"
    assert "queued=3" in scheduler["message"]
    assert "stale_starts=1" in scheduler["message"]


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


def test_rebuild_uses_live_daemon_rpc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "run"
    socket_path = tmp_path / "daemon.sock"
    monkeypatch.setattr(
        lifecycle,
        "_inspect_daemon",
        lambda _args: lifecycle._DaemonInspection(
            state="running",
            paths=lifecycle._DaemonRuntimePaths(
                sase_home=tmp_path / "home",
                run_root=run_root,
                socket_path=socket_path,
                metadata_path=run_root / "daemon.lock.json",
            ),
            metadata=_metadata(1234, "host"),
            rpc={"available": True, "health": {"status": "ok"}},
        ),
    )

    class FakeClient:
        def __init__(self, socket_path_arg: Path, *, timeout: float) -> None:
            assert socket_path_arg == socket_path
            assert timeout == 3

        def rebuild(
            self,
            *,
            storage_reset_only: bool,
            surface: str,
            project_id: str | None,
        ) -> dict[str, Any]:
            assert storage_reset_only is False
            assert surface == "beads"
            assert project_id == "demo"
            return {"mode": "projection_storage_rebuild"}

        def health(self) -> dict[str, Any]:
            return {
                "details": {
                    "projection_db": {
                        "source_exports": {
                            "state": "ok",
                            "pending": 0,
                            "failed": 0,
                            "conflict": 0,
                        }
                    }
                }
            }

    monkeypatch.setattr("sase.daemon.client.LocalDaemonClient", FakeClient)

    payload = lifecycle._run_daemon_rebuild(  # noqa: SLF001
        _args(rebuild_timeout=3, surface="beads", project_id="demo")
    )

    assert payload == {
        "mode": "projection_storage_rebuild",
        "source": "live_daemon_rpc",
        "source_exports": {
            "state": "ok",
            "pending": 0,
            "failed": 0,
            "conflict": 0,
        },
    }


def test_projection_maintenance_uses_live_daemon_rpc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "run"
    socket_path = tmp_path / "daemon.sock"
    monkeypatch.setattr(
        lifecycle,
        "_inspect_daemon",
        lambda _args: lifecycle._DaemonInspection(
            state="running",
            paths=lifecycle._DaemonRuntimePaths(
                sase_home=tmp_path / "home",
                run_root=run_root,
                socket_path=socket_path,
                metadata_path=run_root / "daemon.lock.json",
            ),
            metadata=_metadata(1234, "host"),
            rpc={"available": True, "health": {"status": "ok"}},
        ),
    )
    calls: list[tuple[str, Any]] = []

    class FakeClient:
        def __init__(self, socket_path_arg: Path, *, timeout: float) -> None:
            assert socket_path_arg == socket_path
            assert timeout == 3

        def checkpoint(self, *, mode: str) -> dict[str, Any]:
            calls.append(("checkpoint", mode))
            return {"report": {"mode": mode}}

        def backup(self, *, path: str | None) -> dict[str, Any]:
            calls.append(("backup", path))
            return {"report": {"path": path or "auto.sqlite"}}

        def list_backups(self, *, limit: int) -> dict[str, Any]:
            calls.append(("list", limit))
            return {"backups": {"backups": []}}

        def restore(
            self,
            *,
            path: str,
            live_recovery: bool,
            allow_host_mismatch: bool,
        ) -> dict[str, Any]:
            calls.append(("restore", (path, live_recovery, allow_host_mismatch)))
            return {"report": {"projection_only": True}}

    monkeypatch.setattr("sase.daemon.client.LocalDaemonClient", FakeClient)

    assert (
        lifecycle._run_daemon_checkpoint(  # noqa: SLF001
            _args(checkpoint_timeout=3, mode="truncate")
        )["source"]
        == "live_daemon_rpc"
    )
    assert (
        lifecycle._run_daemon_backup(  # noqa: SLF001
            _args(backup_timeout=3, backup_path="manual.sqlite")
        )["source"]
        == "live_daemon_rpc"
    )
    assert (
        lifecycle._run_daemon_list_backups(  # noqa: SLF001
            _args(list_backups_timeout=3, limit=7)
        )["source"]
        == "live_daemon_rpc"
    )
    assert (
        lifecycle._run_daemon_restore(  # noqa: SLF001
            _args(
                restore_timeout=3,
                path=str(run_root / "backups" / "manual.sqlite"),
                live_recovery=True,
                allow_host_mismatch=True,
            )
        )["source"]
        == "live_daemon_rpc"
    )

    assert calls == [
        ("checkpoint", "truncate"),
        ("backup", "manual.sqlite"),
        ("list", 7),
        ("restore", (str(run_root / "backups" / "manual.sqlite"), True, True)),
    ]


def test_live_restore_requires_explicit_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "run"
    monkeypatch.setattr(
        lifecycle,
        "_inspect_daemon",
        lambda _args: lifecycle._DaemonInspection(
            state="running",
            paths=lifecycle._DaemonRuntimePaths(
                sase_home=tmp_path / "home",
                run_root=run_root,
                socket_path=tmp_path / "daemon.sock",
                metadata_path=run_root / "daemon.lock.json",
            ),
            metadata=_metadata(1234, "host"),
            rpc={"available": True, "health": {"status": "ok"}},
        ),
    )

    with pytest.raises(_DaemonLifecycleError, match="--live-recovery"):
        lifecycle._run_daemon_restore(  # noqa: SLF001
            _args(path=str(run_root / "backups" / "manual.sqlite"))
        )


def test_offline_restore_copies_projection_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "run"
    backup = run_root / "backups" / "manual.sqlite"
    backup.parent.mkdir(parents=True)
    with sqlite3.connect(backup) as conn:
        conn.execute("CREATE TABLE event_log(seq INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO event_log(seq) VALUES (1)")
    backup.with_name(backup.name + ".json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "backup_format_version": 1,
                "host_identity": "test-host",
                "event_max_sequence": 1,
            }
        ),
        encoding="utf-8",
    )
    source_store = tmp_path / "home" / "projects" / "demo.sase"
    source_store.parent.mkdir(parents=True)
    source_store.write_text("NAME: source\n", encoding="utf-8")
    monkeypatch.setenv("HOSTNAME", "test-host")
    monkeypatch.setattr(
        lifecycle,
        "_inspect_daemon",
        lambda _args: lifecycle._DaemonInspection(
            state="stopped",
            paths=lifecycle._DaemonRuntimePaths(
                sase_home=tmp_path / "home",
                run_root=run_root,
                socket_path=tmp_path / "daemon.sock",
                metadata_path=run_root / "daemon.lock.json",
            ),
            message="not running",
        ),
    )

    payload = lifecycle._run_daemon_restore(  # noqa: SLF001
        _args(path=str(backup))
    )

    restored = run_root / "projections" / "projection.sqlite"
    assert payload["source"] == "offline_projection_restore"
    assert payload["report"]["projection_only"] is True
    assert restored.is_file()
    assert source_store.read_text(encoding="utf-8") == "NAME: source\n"
