"""Tests for the SASE mobile gateway Python integration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.integrations.mobile_gateway import (
    _MobileGatewayConfig,
    _MobileGatewayError,
    _load_mobile_gateway_config,
    _prepare_mobile_gateway_launch,
    _run_mobile_gateway_start,
)
from sase.main.parser import create_parser


def _args(**overrides: Any) -> argparse.Namespace:
    values = {
        "bind_address": None,
        "port": None,
        "state_dir": None,
        "allow_non_loopback": False,
        "gateway_command": None,
        "startup_timeout": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_load_mobile_gateway_config_defaults() -> None:
    with patch("sase.integrations.mobile_gateway.load_merged_config", return_value={}):
        assert _load_mobile_gateway_config() == _MobileGatewayConfig()


def test_load_mobile_gateway_config_normalizes_values(tmp_path: Path) -> None:
    with patch(
        "sase.integrations.mobile_gateway.load_merged_config",
        return_value={
            "mobile_gateway": {
                "bind_address": " 127.0.0.1 ",
                "port": "7630",
                "state_dir": str(tmp_path / "state"),
                "allow_non_loopback": True,
                "command": "sase_gateway --extra",
                "startup_timeout_seconds": "2.5",
            }
        },
    ):
        assert _load_mobile_gateway_config() == _MobileGatewayConfig(
            bind_address="127.0.0.1",
            port=7630,
            state_dir=tmp_path / "state",
            allow_non_loopback=True,
            command=("sase_gateway", "--extra"),
            startup_timeout_seconds=2.5,
        )


def test_prepare_launch_builds_default_loopback_argv() -> None:
    launch = _prepare_mobile_gateway_launch(
        _args(),
        config=_MobileGatewayConfig(command=("sase_gateway",)),
    )

    assert launch.argv == ["sase_gateway", "--bind", "127.0.0.1:7629"]
    assert launch.url == "http://127.0.0.1:7629"


def test_prepare_launch_rejects_non_loopback_without_opt_in() -> None:
    with pytest.raises(_MobileGatewayError, match="refusing to bind"):
        _prepare_mobile_gateway_launch(
            _args(bind_address="0.0.0.0"),
            config=_MobileGatewayConfig(command=("sase_gateway",)),
        )


def test_prepare_launch_propagates_non_loopback_opt_in() -> None:
    launch = _prepare_mobile_gateway_launch(
        _args(bind_address="0.0.0.0", allow_non_loopback=True),
        config=_MobileGatewayConfig(command=("sase_gateway",)),
    )

    assert launch.argv == [
        "sase_gateway",
        "--bind",
        "0.0.0.0:7629",
        "--allow-non-loopback",
    ]
    assert launch.url == "http://127.0.0.1:7629"


def test_prepare_launch_missing_binary_error_text() -> None:
    with (
        patch(
            "sase.integrations.mobile_gateway._resolve_gateway_command", return_value=()
        ),
        pytest.raises(_MobileGatewayError, match="mobile gateway binary not found"),
    ):
        _prepare_mobile_gateway_launch(_args(), config=_MobileGatewayConfig())


def test_prepare_launch_includes_state_dir_and_cli_overrides(tmp_path: Path) -> None:
    launch = _prepare_mobile_gateway_launch(
        _args(port=9999, state_dir=str(tmp_path), gateway_command="/bin/sase_gateway"),
        config=_MobileGatewayConfig(command=("ignored",)),
    )

    assert launch.argv == [
        "/bin/sase_gateway",
        "--bind",
        "127.0.0.1:9999",
        "--sase-home",
        str(tmp_path),
    ]


def test_parser_accepts_mobile_gateway_start() -> None:
    args = create_parser().parse_args(
        [
            "mobile",
            "gateway",
            "start",
            "-b",
            "127.0.0.1",
            "-p",
            "7630",
            "-H",
            "/tmp/sase",
            "-L",
            "-c",
            "sase_gateway",
            "-T",
            "1",
        ]
    )

    assert args.command == "mobile"
    assert args.mobile_subcommand == "gateway"
    assert args.mobile_gateway_subcommand == "start"
    assert args.bind_address == "127.0.0.1"
    assert args.port == 7630
    assert args.state_dir == "/tmp/sase"
    assert args.allow_non_loopback is True
    assert args.gateway_command == "sase_gateway"
    assert args.startup_timeout == 1


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class _FakeProcess:
    def __init__(self) -> None:
        self.argv: list[str] | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True


def test_run_mobile_gateway_start_foreground_lifecycle(
    capsys: pytest.CaptureFixture[str],
) -> None:
    proc = _FakeProcess()
    requests: list[tuple[str, str, bytes | None]] = []

    def fake_popen(argv: list[str]) -> _FakeProcess:
        proc.argv = argv
        return proc

    def fake_opener(request: Any, timeout: float) -> _FakeResponse:
        requests.append((request.get_method(), request.full_url, request.data))
        if request.get_method() == "GET":
            return _FakeResponse({"status": "ok"})
        return _FakeResponse(
            {
                "pairing_id": "pair_123",
                "code": "123456",
                "expires_at": "2026-05-06T15:00:00Z",
            }
        )

    with patch(
        "sase.integrations.mobile_gateway.load_merged_config",
        return_value={
            "mobile_gateway": {
                "command": "sase_gateway",
                "startup_timeout_seconds": 1,
            }
        },
    ):
        code = _run_mobile_gateway_start(
            _args(),
            popen=fake_popen,  # type: ignore[arg-type]
            opener=fake_opener,
            sleep=lambda _seconds: None,
        )

    out = capsys.readouterr().out
    assert code == 0
    assert proc.argv == ["sase_gateway", "--bind", "127.0.0.1:7629"]
    assert requests == [
        ("GET", "http://127.0.0.1:7629/api/v1/health", None),
        (
            "POST",
            "http://127.0.0.1:7629/api/v1/session/pair/start",
            b'{"schema_version": 1}',
        ),
    ]
    assert "Starting SASE mobile gateway at http://127.0.0.1:7629" in out
    assert "Pairing code: 123456" in out
    assert "Pairing ID: pair_123" in out
