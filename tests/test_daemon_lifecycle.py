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
