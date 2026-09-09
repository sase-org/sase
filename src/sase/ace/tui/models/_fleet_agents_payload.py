"""Federation response payload traversal helpers for fleet-agent rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def host_payloads(response: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    hosts = response.get("hosts")
    if isinstance(hosts, Sequence) and not isinstance(hosts, (str, bytes, bytearray)):
        return tuple(host for host in hosts if isinstance(host, Mapping))
    if summary_payloads(response):
        return (response,)
    result = response.get("result")
    if isinstance(result, Mapping):
        return host_payloads(result)
    return ()


def summary_payloads(host: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    for key in ("summaries", "agents", "rows"):
        value = host.get(key)
        if isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            return tuple(item for item in value if isinstance(item, Mapping))
    result = host.get("result")
    if isinstance(result, Mapping):
        return summary_payloads(result)
    return ()


def attention_index_by_logical_key(
    response: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if response is None or response.get("disabled"):
        return result
    for host in host_payloads(response):
        for entry in _attention_entries_from_host(host):
            logical_key = entry.get("logical_key")
            if not isinstance(logical_key, str) or not logical_key:
                continue
            existing = result.get(logical_key)
            if existing is None or (
                existing.get("state") != "pending" and entry.get("state") == "pending"
            ):
                result[logical_key] = dict(entry)
    return result


def _attention_entries_from_host(
    host: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    payload = host.get("payload")
    if isinstance(payload, Mapping):
        entries = payload.get("entries")
        if isinstance(entries, Sequence) and not isinstance(
            entries,
            (str, bytes, bytearray),
        ):
            return tuple(item for item in entries if isinstance(item, Mapping))
    result = host.get("result")
    if isinstance(result, Mapping):
        return _attention_entries_from_host(result)
    return ()


def diagnostics_from_response(
    response: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    if response is None:
        return ()
    diagnostics = response.get("diagnostics")
    if not isinstance(diagnostics, Sequence) or isinstance(
        diagnostics,
        (str, bytes, bytearray),
    ):
        return ()
    return tuple(dict(item) for item in diagnostics if isinstance(item, Mapping))


def configured_host_count(response: Mapping[str, Any] | None) -> int:
    if response is None:
        return 0
    configured = response.get("configured_hosts")
    if isinstance(configured, int) and configured >= 0:
        return configured
    hosts = host_payloads(response)
    return len(hosts)
