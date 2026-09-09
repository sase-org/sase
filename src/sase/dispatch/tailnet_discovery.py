"""Built-in Tailscale tailnet discovery for remote dispatch."""

from __future__ import annotations

from collections.abc import Mapping
import json
import time
from typing import Any

from sase.core.machine_setup_facade import classify_tailnet_discovery

from ._tailnet_common import (
    _TAILNET_DEFAULT_PROBE_TIMEOUT_SECONDS,
    _TAILNET_HEALTH_MAX_BYTES,
    _TAILNET_MIN_TIMEOUT_SECONDS,
    config_positive_float,
    config_positive_int,
    positive_timeout,
    safe_text,
)
from ._tailnet_health import (
    HealthObservation,
    HealthProbeResult,
    classify_tailnet_health_payload,
    collect_tailnet_health_observation,
    diagnostic_from_wire,
    probe_tailnet_health,
)
from ._tailnet_status import (
    BoundedCommandResult,
    run_command_bounded,
    run_tailscale_status,
    tailscale_status_argv,
)
from .models import DiscoveryCandidate, DiscoveryResult, MachineDiagnostic

# Preserve this module's historical private test surface after splitting helpers out.
_BoundedCommandResult = BoundedCommandResult
_HealthObservation = HealthObservation
_HealthProbeResult = HealthProbeResult
_classify_tailnet_health_payload = classify_tailnet_health_payload
_collect_tailnet_health_observation = collect_tailnet_health_observation
_config_positive_float = config_positive_float
_config_positive_int = config_positive_int
_positive_timeout = positive_timeout
_probe_tailnet_health = probe_tailnet_health
_run_command_bounded = run_command_bounded
_run_tailscale_status = run_tailscale_status
_safe_text = safe_text
_tailscale_status_argv = tailscale_status_argv


def discover_tailnet(
    config: Mapping[str, Any],
    timeout_seconds: float,
) -> DiscoveryResult:
    """Discover tailnet peers and probe their public gateway health endpoints."""
    timeout = _positive_timeout(timeout_seconds)
    deadline = time.monotonic() + timeout
    status = _run_tailscale_status(config, timeout)
    if status.error_code:
        return DiscoveryResult(
            diagnostics=(
                MachineDiagnostic(
                    code=f"tailnet_{status.error_code}",
                    severity="error",
                    message=status.error_message,
                ),
            )
        )
    if status.returncode != 0:
        stderr = _safe_text(status.stderr).strip()
        suffix = f": {stderr}" if stderr else ""
        return DiscoveryResult(
            diagnostics=(
                MachineDiagnostic(
                    code="tailnet_status_failed",
                    severity="error",
                    message=f"tailscale status --json failed{suffix}",
                ),
            )
        )

    try:
        payload = json.loads(status.stdout.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - normalize unsafe command output.
        return DiscoveryResult(
            diagnostics=(
                MachineDiagnostic(
                    code="tailnet_status_malformed",
                    severity="error",
                    message=(
                        "tailscale status --json returned malformed JSON: "
                        f"{type(exc).__name__}"
                    ),
                ),
            )
        )

    overrides = _endpoint_overrides(config)
    probe_timeout = _config_positive_float(
        config,
        "probe_timeout_seconds",
        _TAILNET_DEFAULT_PROBE_TIMEOUT_SECONDS,
    )
    probe_max_bytes = _config_positive_int(
        config,
        "probe_max_bytes",
        _TAILNET_HEALTH_MAX_BYTES,
    )
    classified = classify_tailnet_discovery(
        {
            "schema_version": 1,
            "status": payload,
            "endpoint_overrides": overrides,
            "health_observations": [],
        }
    )
    observations: list[dict[str, Any]] = []
    deadline_hit = False
    for peer in classified.get("peers") or ():
        if not isinstance(peer, Mapping):
            continue
        endpoint = str(peer.get("endpoint") or "")
        if not endpoint:
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            deadline_hit = True
            break
        observation = _collect_tailnet_health_observation(
            endpoint,
            timeout_seconds=max(
                _TAILNET_MIN_TIMEOUT_SECONDS,
                min(probe_timeout, remaining),
            ),
            max_response_bytes=probe_max_bytes,
        )
        observations.append(observation.to_wire())

    classified = classify_tailnet_discovery(
        {
            "schema_version": 1,
            "status": payload,
            "endpoint_overrides": overrides,
            "health_observations": observations,
        }
    )
    diagnostics = [
        item
        for item in (
            diagnostic_from_wire(raw) for raw in classified.get("diagnostics") or ()
        )
        if item is not None
    ]
    if deadline_hit:
        diagnostics.append(
            MachineDiagnostic(
                code="tailnet_discovery_deadline",
                severity="error",
                message="tailnet discovery exceeded the overall deadline",
            )
        )
    candidates = tuple(
        _candidate_from_wire(raw) for raw in classified.get("candidates") or ()
    )
    return DiscoveryResult(candidates=candidates, diagnostics=tuple(diagnostics))


def _endpoint_overrides(config: Mapping[str, Any]) -> dict[str, str]:
    raw = config.get("endpoint_overrides", config.get("endpoints", {}))
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(key): value
        for key, value in raw.items()
        if isinstance(value, str) and value
    }


def _candidate_from_wire(raw: object) -> DiscoveryCandidate:
    payload = raw if isinstance(raw, Mapping) else {}
    return DiscoveryCandidate(
        provider_ref=str(payload.get("provider_ref") or "builtin@tailnet"),
        endpoint=str(payload.get("endpoint") or ""),
        display_name=str(payload.get("display_name") or ""),
        machine_selector=str(payload.get("machine_selector") or ""),
        installation_pin=str(payload.get("installation_pin") or ""),
        detail=str(payload.get("detail") or ""),
    )


__all__ = ["discover_tailnet"]
