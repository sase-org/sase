"""Built-in Tailscale tailnet discovery for remote dispatch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import os
import selectors
import shlex
import ssl
import subprocess
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from .models import (
    DiscoveryCandidate,
    DiscoveryResult,
    FLEET_PROTOCOL_VERSION,
    MachineDiagnostic,
)

_TAILSCALE_STATUS_MAX_BYTES = 1024 * 1024
_TAILSCALE_STDERR_MAX_BYTES = 16 * 1024
_TAILNET_HEALTH_MAX_BYTES = 64 * 1024
_TAILNET_HEALTH_PATH = "/api/v1/health"
_TAILNET_DEFAULT_PROBE_TIMEOUT_SECONDS = 1.0
_TAILNET_MIN_TIMEOUT_SECONDS = 0.001


@dataclass(frozen=True)
class _BoundedCommandResult:
    """Output from a subprocess that was supervised with hard caps."""

    stdout: bytes = b""
    stderr: bytes = b""
    returncode: int | None = None
    error_code: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class _HealthProbeResult:
    """Compatibility classification for one candidate endpoint."""

    compatibility: str
    reason: str
    diagnostic: MachineDiagnostic | None = None


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


def _run_tailscale_status(
    config: Mapping[str, Any],
    timeout_seconds: float,
) -> _BoundedCommandResult:
    status_timeout = _config_positive_float(
        config,
        "status_timeout_seconds",
        timeout_seconds,
    )
    max_bytes = _config_positive_int(
        config,
        "status_max_bytes",
        _TAILSCALE_STATUS_MAX_BYTES,
    )
    return _run_command_bounded(
        _tailscale_status_argv(config),
        timeout_seconds=min(timeout_seconds, status_timeout),
        max_stdout_bytes=max_bytes,
    )


def _run_command_bounded(
    argv: Sequence[str],
    *,
    timeout_seconds: float,
    max_stdout_bytes: int,
) -> _BoundedCommandResult:
    timeout = _positive_timeout(timeout_seconds)
    try:
        proc = subprocess.Popen(  # noqa: S603 - argv is explicit, no shell.
            list(argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
    except FileNotFoundError:
        return _BoundedCommandResult(
            error_code="status_unavailable",
            error_message="tailscale CLI is not installed or not on PATH",
        )
    except OSError as exc:
        return _BoundedCommandResult(
            error_code="status_unavailable",
            error_message=f"tailscale status could not start: {type(exc).__name__}",
        )

    selector = selectors.DefaultSelector()
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    stdout_total = 0
    stderr_total = 0
    if proc.stdout is not None:
        selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
    if proc.stderr is not None:
        selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_process(proc)
                return _BoundedCommandResult(
                    stdout=b"".join(stdout_chunks),
                    stderr=b"".join(stderr_chunks),
                    error_code="status_timeout",
                    error_message=f"tailscale status --json exceeded {timeout:g}s",
                )
            events = selector.select(remaining)
            if not events:
                continue
            for key, _mask in events:
                stream = key.fileobj
                fd = stream if isinstance(stream, int) else stream.fileno()
                chunk = os.read(fd, 65536)
                if not chunk:
                    selector.unregister(stream)
                    close = getattr(stream, "close", None)
                    if callable(close):
                        close()
                    continue
                if key.data == "stdout":
                    stdout_total += len(chunk)
                    if stdout_total > max_stdout_bytes:
                        _kill_process(proc)
                        return _BoundedCommandResult(
                            stdout=b"".join(stdout_chunks),
                            stderr=b"".join(stderr_chunks),
                            error_code="status_output_too_large",
                            error_message=(
                                "tailscale status --json exceeded the output size "
                                f"limit of {max_stdout_bytes} bytes"
                            ),
                        )
                    stdout_chunks.append(chunk)
                else:
                    allowed = max(0, _TAILSCALE_STDERR_MAX_BYTES - stderr_total)
                    if allowed:
                        stderr_chunks.append(chunk[:allowed])
                    stderr_total += len(chunk)
        return _BoundedCommandResult(
            stdout=b"".join(stdout_chunks),
            stderr=b"".join(stderr_chunks),
            returncode=proc.wait(timeout=0),
        )
    finally:
        selector.close()


def _kill_process(proc: subprocess.Popen[bytes]) -> None:
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.communicate(timeout=1)
    except Exception:  # noqa: BLE001 - process is already being abandoned.
        pass


def _tailscale_status_argv(config: Mapping[str, Any]) -> tuple[str, ...]:
    command = config.get("command", config.get("tailscale_command", "tailscale"))
    if isinstance(command, str):
        argv = tuple(shlex.split(command)) or ("tailscale",)
    elif isinstance(command, Sequence) and not isinstance(command, (bytes, bytearray)):
        argv = tuple(str(part) for part in command if str(part))
    else:
        argv = ("tailscale",)
    return (*argv, "status", "--json")


def _endpoint_overrides(config: Mapping[str, Any]) -> Mapping[str, Any]:
    overrides = config.get("endpoint_overrides", config.get("endpoints", {}))
    return overrides if isinstance(overrides, Mapping) else {}


def _tailnet_peer_endpoint(
    peer_key: str,
    peer: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> tuple[str, str, tuple[MachineDiagnostic, ...]]:
    label = _tailnet_peer_label(peer_key, peer)
    override = _matching_endpoint_override(peer_key, peer, overrides)
    if override is not None:
        if _valid_https_endpoint(override):
            return override, "override", ()
        return (
            "",
            "override",
            (
                MachineDiagnostic(
                    code="tailnet_endpoint_override_invalid",
                    severity="error",
                    alias=label,
                    message=f"{label} endpoint override must be a valid HTTPS URL",
                ),
            ),
        )

    dns_name = _normalized_magic_dns(peer.get("DNSName"))
    if dns_name is None:
        return (
            "",
            "dns",
            (
                MachineDiagnostic(
                    code="tailnet_peer_dns_invalid",
                    severity="warning",
                    alias=label,
                    message=f"{label} did not report a valid MagicDNS name",
                ),
            ),
        )
    return f"https://{dns_name}", "dns", ()


def _matching_endpoint_override(
    peer_key: str,
    peer: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> str | None:
    identities = _peer_identity_values(peer_key, peer)
    for identity in identities:
        raw = overrides.get(identity)
        if isinstance(raw, str) and raw:
            return raw
    return None


def _peer_identity_values(peer_key: str, peer: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = [peer_key]
    for field in ("ID", "PublicKey", "HostName", "DNSName", "Name"):
        raw = peer.get(field)
        if isinstance(raw, str) and raw:
            values.append(raw)
            normalized_dns = _normalized_magic_dns(raw)
            if normalized_dns is not None:
                values.append(normalized_dns)
    ips = peer.get("TailscaleIPs")
    if isinstance(ips, Sequence) and not isinstance(ips, (str, bytes, bytearray)):
        values.extend(str(item) for item in ips if isinstance(item, str) and item)
    return _unique_strings(values)


def _is_self_peer(
    peer_key: str,
    peer: Mapping[str, Any],
    self_peer: Mapping[str, Any],
) -> bool:
    if peer.get("Self") is True:
        return True
    if not self_peer:
        return False
    peer_values = set(_peer_identity_values(peer_key, peer))
    self_values = set(_peer_identity_values("self", self_peer))
    return bool(peer_values & self_values)


def _normalized_magic_dns(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().rstrip(".").casefold()
    if not candidate or len(candidate) > 253 or "." not in candidate:
        return None
    labels = candidate.split(".")
    if any(not _valid_dns_label(label) for label in labels):
        return None
    return candidate


def _valid_dns_label(label: str) -> bool:
    if not label or len(label) > 63:
        return False
    if label[0] == "-" or label[-1] == "-":
        return False
    return all(char.isalnum() or char == "-" for char in label)


def _valid_https_endpoint(value: str) -> bool:
    if any(char.isspace() for char in value):
        return False
    parsed = urllib.parse.urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _tailnet_peer_label(peer_key: str, peer: Mapping[str, Any]) -> str:
    for field in ("HostName", "DNSName", "Name", "ID"):
        raw = peer.get(field)
        if isinstance(raw, str) and raw:
            if field == "DNSName":
                return _normalized_magic_dns(raw) or raw.strip().rstrip(".")
            return raw
    return peer_key


def _tailnet_peer_os(peer: Mapping[str, Any]) -> str:
    for field in ("OS", "os"):
        raw = peer.get(field)
        if isinstance(raw, str) and raw:
            return raw.casefold()
    hostinfo = peer.get("Hostinfo")
    if isinstance(hostinfo, Mapping):
        raw = hostinfo.get("OS")
        if isinstance(raw, str) and raw:
            return raw.casefold()
    return ""


def _tailnet_candidate_detail(
    *,
    compatibility: str,
    probe_reason: str,
    online: bool | None,
    os_hint: str,
    endpoint_source: str,
) -> str:
    parts = [f"compatibility={compatibility}"]
    if probe_reason:
        parts.append(probe_reason)
    if online is True:
        parts.append("tailscale=online")
    elif online is False:
        parts.append("tailscale=offline")
    else:
        parts.append("tailscale=unknown")
    if os_hint:
        parts.append(f"os={os_hint}")
    parts.append(f"endpoint={endpoint_source}")
    return "; ".join(parts)


def _probe_tailnet_health(
    endpoint: str,
    *,
    timeout_seconds: float,
    max_response_bytes: int,
    alias: str,
) -> _HealthProbeResult:
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
        return _HealthProbeResult(
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
        return _HealthProbeResult(
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
        return _HealthProbeResult(
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
        return _HealthProbeResult(
            compatibility="incompatible",
            reason="health response was not an object",
            diagnostic=MachineDiagnostic(
                code="tailnet_probe_unrelated_service",
                severity="warning",
                alias=alias,
                message=f"{alias} returned non-object health JSON",
            ),
        )
    return _classify_tailnet_health_payload(payload, alias=alias)


def _classify_tailnet_health_payload(
    payload: Mapping[str, Any],
    *,
    alias: str,
) -> _HealthProbeResult:
    fleet = payload.get("fleet")
    if fleet is None:
        status = payload.get("status")
        if status == "ok":
            return _HealthProbeResult(
                compatibility="unknown",
                reason="health response has no fleet advertisement",
                diagnostic=MachineDiagnostic(
                    code="tailnet_probe_fleet_unknown",
                    severity="info",
                    alias=alias,
                    message=f"{alias} health did not advertise fleet protocol support",
                ),
            )
        return _HealthProbeResult(
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
        return _HealthProbeResult(
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
        return _HealthProbeResult(
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
        return _HealthProbeResult(
            compatibility="compatible",
            reason=f"fleet protocol v{FLEET_PROTOCOL_VERSION} advertised",
        )
    return _HealthProbeResult(
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
) -> _HealthProbeResult:
    return _HealthProbeResult(
        compatibility="unknown",
        reason=reason,
        diagnostic=MachineDiagnostic(
            code=code,
            severity="warning",
            alias=alias,
            message=f"{alias} health probe failed: {reason}",
        ),
    )


def _unique_strings(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _config_positive_float(
    config: Mapping[str, Any],
    key: str,
    default: float,
) -> float:
    value = config.get(key)
    if value is None or isinstance(value, bool):
        return default
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return default
    return candidate if candidate > 0 else default


def _config_positive_int(
    config: Mapping[str, Any],
    key: str,
    default: int,
) -> int:
    value = config.get(key)
    if value is None or isinstance(value, bool):
        return default
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        return default
    return candidate if candidate > 0 else default


def _positive_timeout(value: float) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = _TAILNET_MIN_TIMEOUT_SECONDS
    return max(_TAILNET_MIN_TIMEOUT_SECONDS, timeout)


def _safe_text(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


__all__ = ["discover_tailnet"]
