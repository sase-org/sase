"""Bounded HTTP client for the Fleet gateway API v1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .models import (
    DISPATCH_SCHEMA_VERSION,
    FLEET_API_BASE_PATH,
    FLEET_PROTOCOL_VERSION,
    BootstrapBundle,
    CredentialRecord,
    EnrollmentResult,
)

_MAX_RESPONSE_BYTES = 64 * 1024


class FleetGatewayError(RuntimeError):
    """Raised for bounded gateway transport or API failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "gateway_error",
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class FleetGatewayClient:
    """Synchronous, timeout-bounded Fleet gateway client."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        opener: object | None = None,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.opener = opener or urllib.request
        self.max_response_bytes = max_response_bytes

    def enroll(
        self,
        *,
        endpoint: str,
        bundle: BootstrapBundle,
        controller: Mapping[str, object],
        requested_scopes: Sequence[str] = (),
    ) -> Mapping[str, Any]:
        body = {
            "schema_version": DISPATCH_SCHEMA_VERSION,
            "bootstrap_id": bundle.bootstrap_id,
            "bootstrap_secret": bundle.bootstrap_secret,
            "pinned_installation_id": bundle.pinned_installation_id,
            "supported_protocol_versions": list(bundle.supported_protocol_versions),
            "requested_scopes": list(requested_scopes or bundle.requested_scopes),
            "controller": {
                "schema_version": DISPATCH_SCHEMA_VERSION,
                **dict(controller),
            },
        }
        return self._request_json("POST", _api_url(endpoint, "enroll"), json_body=body)

    def hello(
        self,
        *,
        endpoint: str,
        credential: CredentialRecord,
        supported_protocol_versions: Sequence[int] = (FLEET_PROTOCOL_VERSION,),
    ) -> Mapping[str, Any]:
        return self._request_json(
            "GET",
            _api_url(endpoint, "hello"),
            bearer_token=credential.token,
            supported_protocol_versions=supported_protocol_versions,
        )

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        bearer_token: str | None = None,
        supported_protocol_versions: Sequence[int] = (FLEET_PROTOCOL_VERSION,),
    ) -> Mapping[str, Any]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https":
            raise FleetGatewayError("fleet gateway endpoint must use HTTPS")
        headers = {
            "Accept": "application/json",
            "X-SASE-Fleet-Protocol-Versions": ",".join(
                str(version) for version in supported_protocol_versions
            ),
        }
        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body, sort_keys=True).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if bearer_token is not None:
            headers["Authorization"] = f"Bearer {bearer_token}"

        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            response = self.opener.urlopen(  # type: ignore[attr-defined]
                request,
                timeout=self.timeout_seconds,
            )
            status = int(getattr(response, "status", 200))
            raw = response.read(self.max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read(self.max_response_bytes + 1)
            if status != 409:
                raise _api_error(status, raw) from exc
        except FleetGatewayError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport details are normalized.
            raise FleetGatewayError(
                f"fleet gateway request failed: {type(exc).__name__}",
                code="transport_failed",
            ) from exc

        if len(raw) > self.max_response_bytes:
            raise FleetGatewayError(
                "fleet gateway response exceeded the response size limit",
                code="payload_too_large",
                status=status,
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - normalize unsafe payload details.
            raise FleetGatewayError(
                "fleet gateway returned invalid JSON",
                code="invalid_response",
                status=status,
            ) from exc
        if not isinstance(payload, Mapping):
            raise FleetGatewayError(
                "fleet gateway returned a non-object response",
                code="invalid_response",
                status=status,
            )
        return payload


def enrollment_result_from_response(
    *,
    alias: str,
    credential_ref: str,
    provider_ref: str,
    endpoint: str,
    payload: Mapping[str, Any],
) -> tuple[EnrollmentResult, CredentialRecord | None]:
    """Normalize a gateway enrollment response without leaking its token."""
    installation = _mapping(payload.get("installation"))
    credential = _mapping(payload.get("credential"))
    capabilities = _mapping(payload.get("capabilities"))
    installation_id = _str(installation.get("installation_id"))
    token = payload.get("token")
    token_type = payload.get("token_type")
    outcome = _str(payload.get("outcome"))
    quarantined = outcome == "quarantined"
    quarantine = _mapping(payload.get("quarantine"))
    quarantine_reason = _str(quarantine.get("reason"))
    protocol_version = payload.get("protocol_version")
    credential_id = _str(credential.get("credential_id"))
    scopes = tuple(
        str(item) for item in credential.get("scopes", ()) if isinstance(item, str)
    )

    credential_record: CredentialRecord | None = None
    if not quarantined:
        if not isinstance(token, str) or not token:
            raise FleetGatewayError(
                "fleet gateway enrollment response did not include a token",
                code="invalid_response",
            )
        if token_type != "bearer":
            raise FleetGatewayError(
                "fleet gateway enrollment response used an unsupported token type",
                code="invalid_response",
            )
        credential_record = CredentialRecord(
            ref=credential_ref,
            token=token,
            token_type=token_type,
            provider_ref=provider_ref,
            endpoint=endpoint,
            installation_id=installation_id,
            credential_id=credential_id,
            scopes=scopes,
            issued_at_unix=_optional_float(credential.get("issued_at_unix")),
            expires_at_unix=_optional_float(credential.get("expires_at_unix")),
        )

    result = EnrollmentResult(
        alias=alias,
        record=None,
        credential_ref=credential_ref,
        machine_selector=_str(payload.get("machine_selector")),
        protocol_version=(
            int(protocol_version) if isinstance(protocol_version, int) else None
        ),
        installation_id=installation_id,
        credential_id=credential_id,
        capabilities=_capability_mapping(capabilities),
        quarantined=quarantined,
        quarantine_reason=quarantine_reason,
    )
    return result, credential_record


def _api_url(endpoint: str, leaf: str) -> str:
    base = endpoint.rstrip("/")
    return f"{base}{FLEET_API_BASE_PATH}/{leaf.lstrip('/')}"


def _api_error(status: int, raw: bytes) -> FleetGatewayError:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        payload = {}
    code = _str(payload.get("code")) if isinstance(payload, Mapping) else ""
    return FleetGatewayError(
        f"fleet gateway request failed with HTTP {status}",
        code=code or "http_error",
        status=status,
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _capability_mapping(raw: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    return {
        key: tuple(str(item) for item in value if isinstance(item, str))
        for key, value in raw.items()
        if isinstance(value, list)
    }


__all__ = [
    "FleetGatewayClient",
    "FleetGatewayError",
    "enrollment_result_from_response",
]
