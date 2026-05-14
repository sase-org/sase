"""Launch preparation tests for daemon lifecycle commands."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.integrations import daemon_lifecycle as lifecycle
from sase.integrations.daemon_lifecycle import (
    _DaemonLifecycleConfig,
    _DaemonLifecycleError,
    _prepare_daemon_launch,
)
from tests._daemon_lifecycle_helpers import _args


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
