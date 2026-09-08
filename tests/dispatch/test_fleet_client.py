"""Fault tests for the synchronous fleet gateway client."""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest

from sase.dispatch.fleet_client import FleetGatewayClient, FleetGatewayError
from sase.dispatch.models import CredentialRecord


def _credential() -> CredentialRecord:
    return CredentialRecord(
        ref="fleet:alpha",
        token="stored-token",
        token_type="bearer",
        provider_ref="builtin@https",
        endpoint="https://fleet.example.test",
        installation_id="sase_inst_v1_" + "a" * 64,
    )


class _FakeOpener:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def urlopen(self, request: Any, *, timeout: float) -> Any:
        del request, timeout
        self.calls += 1
        raise self.error


def _http_error(status: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://fleet.example.test/api/fleet/v1/hello",
        status,
        "error",
        None,  # type: ignore[arg-type]
        io.BytesIO(body),
    )


def test_unauthorized_response_surfaces_status_and_gateway_code() -> None:
    body = json.dumps({"code": "unauthorized", "message": "credential revoked"})
    client = FleetGatewayClient(opener=_FakeOpener(_http_error(401, body.encode())))

    with pytest.raises(FleetGatewayError) as excinfo:
        client.hello(
            endpoint="https://fleet.example.test",
            credential=_credential(),
        )

    assert excinfo.value.status == 401
    assert excinfo.value.code == "unauthorized"
    assert "HTTP 401" in str(excinfo.value)


def test_forbidden_response_without_json_body_keeps_http_status() -> None:
    client = FleetGatewayClient(
        opener=_FakeOpener(_http_error(403, b"<html>forbidden</html>"))
    )

    with pytest.raises(FleetGatewayError) as excinfo:
        client.hello(
            endpoint="https://fleet.example.test",
            credential=_credential(),
        )

    assert excinfo.value.status == 403
    assert excinfo.value.code == "http_error"


def test_non_https_endpoint_is_rejected_before_any_request() -> None:
    opener = _FakeOpener(AssertionError("must not be called"))
    client = FleetGatewayClient(opener=opener)

    with pytest.raises(FleetGatewayError, match="HTTPS"):
        client.hello(
            endpoint="http://fleet.example.test",
            credential=_credential(),
        )

    assert opener.calls == 0
