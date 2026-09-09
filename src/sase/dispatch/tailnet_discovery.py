"""Built-in Tailscale tailnet discovery for remote dispatch."""

from __future__ import annotations

from collections.abc import Mapping
import json
import time
from typing import Any
import urllib.request

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
    HealthProbeResult,
    classify_tailnet_health_payload,
    probe_tailnet_health,
)
from ._tailnet_peers import (
    endpoint_overrides,
    is_self_peer,
    tailnet_candidate_detail,
    tailnet_peer_endpoint,
    tailnet_peer_label,
    tailnet_peer_os,
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
_HealthProbeResult = HealthProbeResult
_classify_tailnet_health_payload = classify_tailnet_health_payload
_config_positive_float = config_positive_float
_config_positive_int = config_positive_int
_endpoint_overrides = endpoint_overrides
_is_self_peer = is_self_peer
_positive_timeout = positive_timeout
_probe_tailnet_health = probe_tailnet_health
_run_command_bounded = run_command_bounded
_run_tailscale_status = run_tailscale_status
_safe_text = safe_text
_tailnet_candidate_detail = tailnet_candidate_detail
_tailnet_peer_endpoint = tailnet_peer_endpoint
_tailnet_peer_label = tailnet_peer_label
_tailnet_peer_os = tailnet_peer_os
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
    if not isinstance(payload, Mapping):
        return DiscoveryResult(
            diagnostics=(
                MachineDiagnostic(
                    code="tailnet_status_malformed",
                    severity="error",
                    message="tailscale status --json returned a non-object payload",
                ),
            )
        )
    return _tailnet_result_from_status(
        payload,
        config=config,
        deadline=deadline,
    )


def _tailnet_result_from_status(
    payload: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    deadline: float,
) -> DiscoveryResult:
    raw_peers = payload.get("Peer", {})
    if raw_peers is None:
        raw_peers = {}
    if not isinstance(raw_peers, Mapping):
        return DiscoveryResult(
            diagnostics=(
                MachineDiagnostic(
                    code="tailnet_status_peer_invalid",
                    severity="error",
                    message="tailscale status Peer payload must be a mapping",
                ),
            )
        )

    self_peer = payload.get("Self")
    self_mapping = self_peer if isinstance(self_peer, Mapping) else {}
    candidates: list[DiscoveryCandidate] = []
    diagnostics: list[MachineDiagnostic] = []
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

    for peer_key, raw_peer in sorted(raw_peers.items(), key=lambda item: str(item[0])):
        if not isinstance(raw_peer, Mapping):
            diagnostics.append(
                MachineDiagnostic(
                    code="tailnet_peer_not_mapping",
                    severity="warning",
                    alias=str(peer_key),
                    message=f"tailnet peer {peer_key} was not an object",
                )
            )
            continue
        if _is_self_peer(str(peer_key), raw_peer, self_mapping):
            continue

        endpoint, endpoint_source, endpoint_diagnostics = _tailnet_peer_endpoint(
            str(peer_key),
            raw_peer,
            overrides,
        )
        diagnostics.extend(endpoint_diagnostics)
        if not endpoint:
            continue

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            diagnostics.append(
                MachineDiagnostic(
                    code="tailnet_discovery_deadline",
                    severity="error",
                    message="tailnet discovery exceeded the overall deadline",
                )
            )
            break

        alias = _tailnet_peer_label(str(peer_key), raw_peer)
        online = raw_peer.get("Online")
        os_hint = _tailnet_peer_os(raw_peer)
        probe = _probe_tailnet_health(
            endpoint,
            timeout_seconds=max(
                _TAILNET_MIN_TIMEOUT_SECONDS,
                min(probe_timeout, remaining),
            ),
            max_response_bytes=probe_max_bytes,
            alias=alias,
        )
        if probe.diagnostic is not None:
            diagnostics.append(probe.diagnostic)
        if online is False:
            diagnostics.append(
                MachineDiagnostic(
                    code="tailnet_peer_offline",
                    severity="info",
                    alias=alias,
                    message=f"{alias} is offline according to tailscale status",
                )
            )
        if os_hint and os_hint not in {"linux", "macos", "darwin"}:
            diagnostics.append(
                MachineDiagnostic(
                    code="tailnet_peer_os_advisory",
                    severity="info",
                    alias=alias,
                    message=f"{alias} reports OS {os_hint}; gateway support is advisory",
                )
            )

        candidates.append(
            DiscoveryCandidate(
                provider_ref="builtin@tailnet",
                endpoint=endpoint,
                display_name=alias,
                detail=_tailnet_candidate_detail(
                    compatibility=probe.compatibility,
                    probe_reason=probe.reason,
                    online=online if isinstance(online, bool) else None,
                    os_hint=os_hint,
                    endpoint_source=endpoint_source,
                ),
            )
        )

    return DiscoveryResult(
        candidates=tuple(candidates),
        diagnostics=tuple(diagnostics),
    )


__all__ = ["discover_tailnet"]
