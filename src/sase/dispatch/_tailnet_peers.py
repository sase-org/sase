"""Peer and endpoint parsing for built-in tailnet discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
import urllib.parse

from ._tailnet_common import unique_strings
from .models import MachineDiagnostic


def endpoint_overrides(config: Mapping[str, Any]) -> Mapping[str, Any]:
    overrides = config.get("endpoint_overrides", config.get("endpoints", {}))
    return overrides if isinstance(overrides, Mapping) else {}


def tailnet_peer_endpoint(
    peer_key: str,
    peer: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> tuple[str, str, tuple[MachineDiagnostic, ...]]:
    label = tailnet_peer_label(peer_key, peer)
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
    return unique_strings(values)


def is_self_peer(
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


def tailnet_peer_label(peer_key: str, peer: Mapping[str, Any]) -> str:
    for field in ("HostName", "DNSName", "Name", "ID"):
        raw = peer.get(field)
        if isinstance(raw, str) and raw:
            if field == "DNSName":
                return _normalized_magic_dns(raw) or raw.strip().rstrip(".")
            return raw
    return peer_key


def tailnet_peer_os(peer: Mapping[str, Any]) -> str:
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


def tailnet_candidate_detail(
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
