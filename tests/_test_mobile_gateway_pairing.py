"""Mobile gateway pairing tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import sase.integrations.mobile_gateway as mobile_gateway
from sase.integrations.mobile_gateway import _MobileGatewayError
from tests._mobile_gateway_test_helpers import (
    ISSUED_PAIRING,
    OWNER_LOCAL_HEALTH,
    FakeResponse,
    capture_issue,
    make_args,
)


def test_run_mobile_gateway_pair_issues_owner_local_challenge(
    capsys: pytest.CaptureFixture[str],
) -> None:
    requests: list[tuple[str, str, bytes | None]] = []
    issued: list[dict[str, Any]] = []

    def fake_opener(request: Any, timeout: float) -> FakeResponse:
        requests.append((request.get_method(), request.full_url, request.data))
        if request.get_method() != "GET":
            raise AssertionError(
                f"unexpected {request.get_method()} {request.full_url}"
            )
        return FakeResponse(OWNER_LOCAL_HEALTH)

    pairing = dict(ISSUED_PAIRING)
    pairing.update(
        {
            "pairing_id": "pair_456",
            "code": "654321",
            "expires_at": "2026-05-06T15:05:00Z",
        }
    )

    def issue(request: dict[str, Any]) -> dict[str, Any]:
        issued.append(request)
        return pairing

    with (
        patch(
            "sase.integrations.mobile_gateway.load_merged_config",
            return_value={"mobile_gateway": {"port": 7630}},
        ),
        patch(
            "sase.integrations.mobile_gateway.require_rust_binding",
            return_value=issue,
        ),
    ):
        code = mobile_gateway._run_mobile_gateway_pair(  # noqa: SLF001
            make_args(),
            opener=fake_opener,
        )

    out = capsys.readouterr().out
    assert code == 0
    assert requests == [
        ("GET", "http://127.0.0.1:7630/api/v1/health", None),
    ]
    assert issued == [{"schema_version": 1}]
    assert "Pairing code: 654321" in out
    assert "Pairing ID: pair_456" in out


def test_run_mobile_gateway_pair_passes_cli_state_dir(
    tmp_path: Path,
) -> None:
    issued: list[dict[str, Any]] = []

    def fake_opener(request: Any, timeout: float) -> FakeResponse:
        return FakeResponse(OWNER_LOCAL_HEALTH)

    with (
        patch(
            "sase.integrations.mobile_gateway.load_merged_config",
            return_value={
                "mobile_gateway": {"state_dir": str(tmp_path / "config-state")}
            },
        ),
        patch(
            "sase.integrations.mobile_gateway.require_rust_binding",
            return_value=capture_issue(issued),
        ),
    ):
        code = mobile_gateway._run_mobile_gateway_pair(  # noqa: SLF001
            make_args(state_dir=str(tmp_path / "cli-state")),
            opener=fake_opener,
        )

    assert code == 0
    assert issued == [
        {
            "schema_version": 1,
            "state_root": str(tmp_path / "cli-state"),
        }
    ]


def test_run_mobile_gateway_pair_uses_config_state_dir(
    tmp_path: Path,
) -> None:
    issued: list[dict[str, Any]] = []

    def fake_opener(request: Any, timeout: float) -> FakeResponse:
        return FakeResponse(OWNER_LOCAL_HEALTH)

    with (
        patch(
            "sase.integrations.mobile_gateway.load_merged_config",
            return_value={
                "mobile_gateway": {"state_dir": str(tmp_path / "config-state")}
            },
        ),
        patch(
            "sase.integrations.mobile_gateway.require_rust_binding",
            return_value=capture_issue(issued),
        ),
    ):
        code = mobile_gateway._run_mobile_gateway_pair(  # noqa: SLF001
            make_args(),
            opener=fake_opener,
        )

    assert code == 0
    assert issued == [
        {
            "schema_version": 1,
            "state_root": str(tmp_path / "config-state"),
        }
    ]


def test_run_mobile_gateway_pair_rejects_old_gateway_without_issuing() -> None:
    def fake_opener(request: Any, timeout: float) -> FakeResponse:
        return FakeResponse({"status": "ok"})

    def fail_binding(_name: str) -> None:
        raise AssertionError("must not issue against an old gateway")

    with (
        patch(
            "sase.integrations.mobile_gateway.load_merged_config",
            return_value={},
        ),
        patch(
            "sase.integrations.mobile_gateway.require_rust_binding",
            side_effect=fail_binding,
        ),
        pytest.raises(_MobileGatewayError, match="upgrade sase_gateway"),
    ):
        mobile_gateway._run_mobile_gateway_pair(  # noqa: SLF001
            make_args(),
            opener=fake_opener,
        )


def test_run_mobile_gateway_pair_wraps_missing_binding() -> None:
    def fake_opener(request: Any, timeout: float) -> FakeResponse:
        return FakeResponse(OWNER_LOCAL_HEALTH)

    with (
        patch(
            "sase.integrations.mobile_gateway.load_merged_config",
            return_value={},
        ),
        patch(
            "sase.integrations.mobile_gateway.require_rust_binding",
            side_effect=AttributeError("mobile_pairing_issue is missing"),
        ),
        pytest.raises(
            _MobileGatewayError,
            match="could not issue owner-local pairing challenge",
        ),
    ):
        mobile_gateway._run_mobile_gateway_pair(  # noqa: SLF001
            make_args(),
            opener=fake_opener,
        )
