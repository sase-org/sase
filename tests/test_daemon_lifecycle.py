"""Tests for the SASE daemon Python lifecycle wrapper."""

from __future__ import annotations

import argparse
import json
import os
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
        "verify_timeout": None,
        "diff_timeout": None,
        "surface": "all",
        "project_id": None,
        "storage_reset_only": False,
        "limit": 100,
        "cursor": None,
        "json_output": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _metadata(pid: int, host: str, **overrides: Any) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "pid": pid,
        "hostname": host,
        "boot_session_hint": "boot",
        "executable_path": "/bin/sase_gateway",
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
    assert payload["metrics_endpoint"] == "http://127.0.0.1:7629/metrics"


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
