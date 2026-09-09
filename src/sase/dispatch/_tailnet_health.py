"""Health endpoint probing for built-in tailnet discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import ssl
from typing import Any
import urllib.error
import urllib.request

from ._tailnet_common import _TAILNET_HEALTH_PATH
from .models import FLEET_PROTOCOL_VERSION, MachineDiagnostic


@dataclass(frozen=True)
class HealthProbeResult:
    """Compatibility classification for one candidate endpoint."""

    compatibility: str
    reason: str
    diagnostic: MachineDiagnostic | None = None


def probe_tailnet_health(
    endpoint: str,
    *,
    timeout_seconds: float,
    max_response_bytes: int,
    alias: str,
) -> HealthProbeResult:
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
        return _health_probe_error(
            alias,
            code="tailnet_probe_timeout",
            reason="health probe timed out",
        )
    except urllib.error.HTTPError as exc:
        return HealthProbeResult(
            compatibility="incompatible",
            reason=f"health returned HTTP {exc.code}",
            diagnostic=MachineDiagnostic(
                code="tailnet_probe_http_error",
                severity="warning",
                alias=alias,
                message=f"{alias} health probe returned HTTP {exc.code}",
            ),
        )
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        code = (
            "tailnet_probe_tls_failed"
            if isinstance(reason, ssl.SSLError)
            else "tailnet_probe_unreachable"
        )
        return _health_probe_error(alias, code=code, reason=type(reason).__name__)
    except ssl.SSLError:
        return _health_probe_error(
            alias,
            code="tailnet_probe_tls_failed",
            reason="TLS handshake failed",
        )
    except OSError as exc:
        return _health_probe_error(
            alias,
            code="tailnet_probe_unreachable",
            reason=type(exc).__name__,
        )

    if len(raw) > max_response_bytes:
        return _health_probe_error(
            alias,
            code="tailnet_probe_oversized",
            reason="health response exceeded the size limit",
        )
    if status < 200 or status >= 300:
        return HealthProbeResult(
            compatibility="incompatible",
            reason=f"health returned HTTP {status}",
            diagnostic=MachineDiagnostic(
                code="tailnet_probe_http_error",
                severity="warning",
                alias=alias,
                message=f"{alias} health probe returned HTTP {status}",
            ),
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001 - probe diagnostics only.
        return HealthProbeResult(
            compatibility="incompatible",
            reason="health response was not JSON",
            diagnostic=MachineDiagnostic(
                code="tailnet_probe_unrelated_service",
                severity="warning",
                alias=alias,
                message=f"{alias} did not return a SASE health JSON response",
            ),
        )
    if not isinstance(payload, Mapping):
        return HealthProbeResult(
            compatibility="incompatible",
            reason="health response was not an object",
            diagnostic=MachineDiagnostic(
                code="tailnet_probe_unrelated_service",
                severity="warning",
                alias=alias,
                message=f"{alias} returned non-object health JSON",
            ),
        )
    return classify_tailnet_health_payload(payload, alias=alias)


def classify_tailnet_health_payload(
    payload: Mapping[str, Any],
    *,
    alias: str,
) -> HealthProbeResult:
    fleet = payload.get("fleet")
    if fleet is None:
        status = payload.get("status")
        if status == "ok":
            return HealthProbeResult(
                compatibility="unknown",
                reason="health response has no fleet advertisement",
                diagnostic=MachineDiagnostic(
                    code="tailnet_probe_fleet_unknown",
                    severity="info",
                    alias=alias,
                    message=f"{alias} health did not advertise fleet protocol support",
                ),
            )
        return HealthProbeResult(
            compatibility="incompatible",
            reason="health response did not look like a SASE gateway",
            diagnostic=MachineDiagnostic(
                code="tailnet_probe_unrelated_service",
                severity="warning",
                alias=alias,
                message=f"{alias} did not return a recognizable SASE health response",
            ),
        )
    if not isinstance(fleet, Mapping):
        return HealthProbeResult(
            compatibility="incompatible",
            reason="fleet advertisement was malformed",
            diagnostic=MachineDiagnostic(
                code="tailnet_probe_fleet_malformed",
                severity="warning",
                alias=alias,
                message=f"{alias} returned a malformed fleet advertisement",
            ),
        )
    versions = fleet.get("supported_protocol_versions")
    if not isinstance(versions, Sequence) or isinstance(
        versions,
        (str, bytes, bytearray),
    ):
        return HealthProbeResult(
            compatibility="incompatible",
            reason="fleet protocol versions were malformed",
            diagnostic=MachineDiagnostic(
                code="tailnet_probe_fleet_malformed",
                severity="warning",
                alias=alias,
                message=f"{alias} returned malformed fleet protocol versions",
            ),
        )
    normalized_versions = {
        int(version)
        for version in versions
        if isinstance(version, int) and not isinstance(version, bool)
    }
    if FLEET_PROTOCOL_VERSION in normalized_versions:
        return HealthProbeResult(
            compatibility="compatible",
            reason=f"fleet protocol v{FLEET_PROTOCOL_VERSION} advertised",
        )
    return HealthProbeResult(
        compatibility="incompatible",
        reason="fleet protocol version is unsupported",
        diagnostic=MachineDiagnostic(
            code="tailnet_probe_fleet_incompatible",
            severity="warning",
            alias=alias,
            message=(
                f"{alias} did not advertise fleet protocol v{FLEET_PROTOCOL_VERSION}"
            ),
        ),
    )


def _health_probe_error(
    alias: str,
    *,
    code: str,
    reason: str,
) -> HealthProbeResult:
    return HealthProbeResult(
        compatibility="unknown",
        reason=reason,
        diagnostic=MachineDiagnostic(
            code=code,
            severity="warning",
            alias=alias,
            message=f"{alias} health probe failed: {reason}",
        ),
    )
