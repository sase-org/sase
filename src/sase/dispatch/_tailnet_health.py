"""Health endpoint probing for built-in tailnet discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import ssl
from typing import Any, Literal
import urllib.error
import urllib.request

from sase.core.machine_setup_facade import classify_tailnet_health

from ._tailnet_common import _TAILNET_HEALTH_PATH
from .models import MachineDiagnostic


@dataclass(frozen=True)
class HealthProbeResult:
    """Compatibility classification for one candidate endpoint."""

    compatibility: str
    reason: str
    diagnostic: MachineDiagnostic | None = None


@dataclass(frozen=True)
class HealthObservation:
    """Host-collected health payload or transport failure for one endpoint."""

    endpoint: str
    payload: Mapping[str, Any] | None = None
    error_code: str = ""
    error_reason: str = ""

    def to_wire(self) -> dict[str, Any]:
        observation: dict[str, Any] = {"endpoint": self.endpoint}
        if self.payload is not None:
            observation["payload"] = dict(self.payload)
        if self.error_code:
            observation["error_code"] = self.error_code
            observation["error_reason"] = self.error_reason
        return observation


def collect_tailnet_health_observation(
    endpoint: str,
    *,
    timeout_seconds: float,
    max_response_bytes: int,
) -> HealthObservation:
    """GET the public health endpoint and return a core-ready observation."""
    url = f"{endpoint.rstrip('/')}{_TAILNET_HEALTH_PATH}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read(max_response_bytes + 1)
    except TimeoutError:
        return HealthObservation(
            endpoint,
            error_code="tailnet_probe_timeout",
            error_reason="health probe timed out",
        )
    except urllib.error.HTTPError as exc:
        return HealthObservation(
            endpoint,
            error_code="tailnet_probe_http_error",
            error_reason=str(exc.code),
        )
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        code = (
            "tailnet_probe_tls_failed"
            if isinstance(reason, ssl.SSLError)
            else "tailnet_probe_unreachable"
        )
        return HealthObservation(
            endpoint,
            error_code=code,
            error_reason=type(reason).__name__,
        )
    except ssl.SSLError:
        return HealthObservation(
            endpoint,
            error_code="tailnet_probe_tls_failed",
            error_reason="TLS handshake failed",
        )
    except OSError as exc:
        return HealthObservation(
            endpoint,
            error_code="tailnet_probe_unreachable",
            error_reason=type(exc).__name__,
        )

    if len(raw) > max_response_bytes:
        return HealthObservation(
            endpoint,
            error_code="tailnet_probe_oversized",
            error_reason="health response exceeded the size limit",
        )
    if status < 200 or status >= 300:
        return HealthObservation(
            endpoint,
            error_code="tailnet_probe_http_error",
            error_reason=str(status),
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001 - probe diagnostics only.
        return HealthObservation(
            endpoint,
            error_code="tailnet_probe_unrelated_service",
            error_reason="did not return a SASE health JSON response",
        )
    if isinstance(payload, Mapping):
        return HealthObservation(endpoint, payload=payload)
    return HealthObservation(endpoint, payload={"_non_object": True})


def probe_tailnet_health(
    endpoint: str,
    *,
    timeout_seconds: float,
    max_response_bytes: int,
    alias: str,
) -> HealthProbeResult:
    observation = collect_tailnet_health_observation(
        endpoint,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
    )
    if observation.error_code:
        return classify_tailnet_health_payload(
            {},
            alias=alias,
            error_code=observation.error_code,
            error_reason=observation.error_reason,
        )
    if observation.payload is None:
        return classify_tailnet_health_payload({}, alias=alias)
    if observation.payload.get("_non_object"):
        return classify_tailnet_health_payload(
            ["non-object"],
            alias=alias,
        )
    return classify_tailnet_health_payload(observation.payload, alias=alias)


def classify_tailnet_health_payload(
    payload: Mapping[str, Any] | Sequence[Any] | None,
    *,
    alias: str,
    error_code: str = "",
    error_reason: str = "",
) -> HealthProbeResult:
    request: dict[str, Any] = {"schema_version": 1, "alias": alias}
    if error_code:
        request["error_code"] = error_code
        request["error_reason"] = error_reason
    elif payload is None:
        request["error_code"] = "tailnet_probe_unrelated_service"
        request["error_reason"] = "health not observed"
    else:
        request["payload"] = payload
    result = classify_tailnet_health(request)
    return HealthProbeResult(
        compatibility=str(result.get("compatibility") or "unknown"),
        reason=str(result.get("reason") or ""),
        diagnostic=diagnostic_from_wire(result.get("diagnostic")),
    )


def diagnostic_from_wire(raw: object) -> MachineDiagnostic | None:
    if not isinstance(raw, Mapping):
        return None
    code = str(raw.get("code") or "")
    if not code:
        return None
    raw_severity = raw.get("severity")
    severity: Literal["info", "warning", "error"] = (
        raw_severity if raw_severity in {"info", "warning", "error"} else "warning"
    )
    return MachineDiagnostic(
        code=code,
        message=str(raw.get("message") or ""),
        severity=severity,
        alias=str(raw.get("alias") or ""),
    )
