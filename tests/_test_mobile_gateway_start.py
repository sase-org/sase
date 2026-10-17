"""Mobile gateway start and service-host ownership tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import sase.integrations.mobile_gateway as mobile_gateway
from sase.integrations.mobile_gateway import _run_mobile_gateway_start
from tests._mobile_gateway_test_helpers import (
    OWNER_LOCAL_HEALTH,
    FakeResponse,
    capture_issue,
    make_args,
)


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


def _gateway_composition(
    *, configured: bool = True, available: bool = True, enabled: bool = True
) -> SimpleNamespace:
    """Stand-in for the composed ``service.procs`` config with a ``gateway`` entry."""
    entry = SimpleNamespace(name="gateway", available=available, enabled=enabled)
    return SimpleNamespace(
        get=lambda name: entry if configured and name == "gateway" else None
    )


def _gateway_state(**enablement: bool) -> SimpleNamespace:
    """Stand-in for the service state with per-proc enablement overrides."""
    return SimpleNamespace(
        state=SimpleNamespace(
            enablement={
                name: SimpleNamespace(enabled=enabled)
                for name, enabled in enablement.items()
            }
        )
    )


def test_run_mobile_gateway_start_foreground_lifecycle(
    capsys: pytest.CaptureFixture[str],
) -> None:
    proc = _FakeProcess()
    requests: list[tuple[str, str, bytes | None]] = []
    issued: list[dict[str, Any]] = []

    def fake_popen(argv: list[str]) -> _FakeProcess:
        proc.argv = argv
        return proc

    def fake_opener(request: Any, timeout: float) -> FakeResponse:
        requests.append((request.get_method(), request.full_url, request.data))
        if request.get_method() != "GET":
            raise AssertionError(
                f"unexpected {request.get_method()} {request.full_url}"
            )
        return FakeResponse(OWNER_LOCAL_HEALTH)

    with (
        patch(
            "sase.integrations.mobile_gateway.load_merged_config",
            return_value={
                "mobile_gateway": {
                    "command": "sase_gateway",
                    "startup_timeout_seconds": 1,
                }
            },
        ),
        patch(
            "sase.integrations.mobile_gateway.require_rust_binding",
            return_value=capture_issue(issued),
        ),
    ):
        code = _run_mobile_gateway_start(
            make_args(),
            popen=fake_popen,  # type: ignore[arg-type]
            opener=fake_opener,
            sleep=lambda _seconds: None,
        )

    out = capsys.readouterr().out
    assert code == 0
    assert proc.argv == ["sase_gateway", "--bind", "127.0.0.1:7629"]
    assert requests == [
        ("GET", "http://127.0.0.1:7629/api/v1/health", None),
    ]
    assert issued == [{"schema_version": 1}]
    assert "Starting SASE mobile gateway at http://127.0.0.1:7629" in out
    assert "Pairing code: 123456" in out
    assert "Pairing ID: pair_123" in out


@pytest.mark.parametrize(
    ("composition", "state", "expected"),
    [
        pytest.param(_gateway_composition(), _gateway_state(), True, id="configured"),
        pytest.param(
            _gateway_composition(configured=False),
            _gateway_state(),
            False,
            id="not-configured",
        ),
        pytest.param(
            _gateway_composition(available=False),
            _gateway_state(),
            False,
            id="unavailable",
        ),
        pytest.param(
            _gateway_composition(enabled=False),
            _gateway_state(),
            False,
            id="configured-disabled",
        ),
        pytest.param(
            _gateway_composition(enabled=False),
            _gateway_state(gateway=True),
            True,
            id="override-enables",
        ),
        pytest.param(
            _gateway_composition(),
            _gateway_state(gateway=False),
            False,
            id="override-disables",
        ),
    ],
)
def test_service_host_owns_gateway_follows_the_configured_entry(
    composition: SimpleNamespace, state: SimpleNamespace, expected: bool
) -> None:
    with (
        patch("sase.service.config.load_service_config", return_value=composition),
        patch("sase.service.state.read_service_state", return_value=state),
    ):
        assert mobile_gateway._service_host_owns_gateway() is expected  # noqa: SLF001


def test_service_host_owns_gateway_is_false_when_service_apis_fail() -> None:
    with patch(
        "sase.service.config.load_service_config",
        side_effect=RuntimeError("older sase without service config"),
    ):
        assert mobile_gateway._service_host_owns_gateway() is False  # noqa: SLF001


def test_run_mobile_gateway_start_delegates_to_service_host(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    def fail_popen(_argv: list[str]) -> None:
        raise AssertionError("foreground gateway must not be spawned")

    with (
        patch(
            "sase.service.config.load_service_config",
            return_value=_gateway_composition(),
        ),
        patch("sase.service.state.read_service_state", return_value=_gateway_state()),
        patch(
            "sase.service.state.clear_service_stop",
            side_effect=lambda name: calls.append(f"clear:{name}"),
        ),
        patch(
            "sase.service.control.start_service_host",
            return_value=SimpleNamespace(ok=True, message="running detached"),
        ),
        patch(
            "sase.service.control.nudge_service_host",
            side_effect=lambda: calls.append("nudge"),
        ),
    ):
        code = _run_mobile_gateway_start(
            make_args(),
            popen=fail_popen,  # type: ignore[arg-type]
        )

    out = capsys.readouterr().out
    assert code == 0
    assert calls == ["clear:gateway", "nudge"]
    assert "managed by the SASE service host" in out
    assert "sase mobile gateway pair" in out
