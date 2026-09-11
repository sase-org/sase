"""Core-normalized federation payload helpers for fleet-agent rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def normalize_response(
    response: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a normalized federation read response, or ``None`` for no response."""
    if response is None:
        return None
    if _is_normalized_response(response):
        return dict(response)
    from sase.dispatch.counts import normalize_fleet_federation_response

    return normalize_fleet_federation_response(response)


def host_payloads(response: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Return core-normalized host envelopes for a federation read response."""
    normalized = normalize_response(response)
    if normalized is None:
        return ()
    hosts = normalized.get("hosts")
    if isinstance(hosts, Sequence) and not isinstance(hosts, (str, bytes, bytearray)):
        return tuple(host for host in hosts if isinstance(host, Mapping))
    return ()


def summary_payloads(host: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Return core-validated summaries from a normalized host envelope."""
    return _mapping_sequence(host.get("summaries"))


def count_hosts_from_response(
    response: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any], ...]:
    """Return normalized count-host inputs suitable for the core count binding."""
    normalized = normalize_response(response)
    if normalized is None:
        return ()
    hosts = normalized.get("count_hosts")
    if isinstance(hosts, Sequence) and not isinstance(hosts, (str, bytes, bytearray)):
        return tuple(host for host in hosts if isinstance(host, Mapping))
    return ()


def attention_index_by_logical_key(
    response: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Index raw fleet-attention entries by logical key."""
    result: dict[str, dict[str, Any]] = {}
    if response is None or response.get("disabled"):
        return result
    for host in _raw_host_payloads(response):
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


def diagnostics_from_response(
    response: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    """Return core-normalized diagnostics for a federation read response."""
    normalized = normalize_response(response)
    if normalized is None:
        return ()
    raw = normalized.get("diagnostics")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return tuple(dict(item) for item in raw if isinstance(item, Mapping))
    return ()


def diagnostics_from_attention_response(
    response: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    """Return raw diagnostics from the fleet-attention response contract."""
    if response is None:
        return ()
    diagnostics: list[dict[str, Any]] = []
    raw = response.get("diagnostics")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        diagnostics.extend(dict(item) for item in raw if isinstance(item, Mapping))
    for host in _raw_host_payloads(response):
        raw_host = host.get("diagnostics")
        if isinstance(raw_host, Sequence) and not isinstance(
            raw_host,
            (str, bytes, bytearray),
        ):
            diagnostics.extend(
                dict(item) for item in raw_host if isinstance(item, Mapping)
            )
    return tuple(diagnostics)


def response_is_partial(response: Mapping[str, Any] | None) -> bool:
    normalized = normalize_response(response)
    if normalized is None:
        return False
    return bool(normalized.get("partial"))


def catalog_next_cursor(response: Mapping[str, Any] | None) -> str | None:
    """Return the first ready catalog continuation cursor, if any."""
    normalized = normalize_response(response)
    if normalized is None:
        return None
    for host in host_payloads(normalized):
        catalog = _catalog(host)
        if catalog is None or catalog.get("state") != "ready":
            continue
        cursor = catalog.get("next_cursor")
        if isinstance(cursor, str) and cursor.strip():
            return cursor.strip()
    return None


def catalog_next_cursors_by_host(
    response: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Return ready catalog continuation cursors keyed by installation ID."""
    normalized = normalize_response(response)
    if normalized is None:
        return {}
    cursors: dict[str, str] = {}
    for host in host_payloads(normalized):
        installation_id = _host_installation_id(host)
        catalog = _catalog(host)
        if (
            installation_id is None
            or catalog is None
            or catalog.get("state") != "ready"
        ):
            continue
        cursor = catalog.get("next_cursor")
        if isinstance(cursor, str) and cursor.strip():
            cursors[installation_id] = cursor.strip()
    return cursors


def merge_catalog_pages(
    first: Mapping[str, Any] | None,
    second: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    """Merge two catalog pages into one normalized response."""
    first_norm = normalize_response(first)
    second_norm = normalize_response(second)
    if first_norm is None:
        return dict(second_norm) if second_norm is not None else None
    if second_norm is None:
        return dict(first_norm)

    merged_hosts: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for host in (*host_payloads(first_norm), *host_payloads(second_norm)):
        key = _host_merge_key(host, len(order))
        existing = merged_hosts.get(key)
        if existing is None:
            merged_hosts[key] = dict(host)
            order.append(key)
            continue
        merged_hosts[key] = _merge_normalized_host_pages(existing, host)

    hosts = [merged_hosts[key] for key in order]
    merged = dict(first_norm)
    merged["operation"] = second_norm.get("operation") or first_norm.get("operation")
    merged["configured_host_count"] = max(
        configured_host_count(first_norm),
        configured_host_count(second_norm),
    )
    merged["hosts"] = hosts
    merged["summaries"] = [
        summary for host in hosts for summary in summary_payloads(host)
    ]
    merged["count_hosts"] = [
        host["count_input"]
        for host in hosts
        if isinstance(host.get("count_input"), Mapping)
    ]
    merged["diagnostics"] = [
        *diagnostics_from_response(first_norm),
        *diagnostics_from_response(second_norm),
    ]
    merged["partial"] = (
        bool(first_norm.get("partial"))
        or bool(second_norm.get("partial"))
        or any(bool(host.get("partial")) for host in hosts)
    )
    return merged


def configured_host_count(response: Mapping[str, Any] | None) -> int:
    normalized = normalize_response(response)
    if normalized is None:
        return 0
    configured = normalized.get("configured_host_count")
    if isinstance(configured, bool):
        return 0
    if isinstance(configured, int) and configured >= 0:
        return configured
    return len(host_payloads(normalized))


def _is_normalized_response(response: Mapping[str, Any]) -> bool:
    return (
        response.get("schema_version") == 1
        and isinstance(response.get("hosts"), Sequence)
        and isinstance(response.get("count_hosts"), Sequence)
        and "configured_host_count" in response
    )


def _raw_host_payloads(response: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    hosts = response.get("hosts")
    if isinstance(hosts, Sequence) and not isinstance(hosts, (str, bytes, bytearray)):
        return tuple(host for host in hosts if isinstance(host, Mapping))
    result = response.get("result")
    if isinstance(result, Mapping):
        return _raw_host_payloads(result)
    return ()


def _mapping_sequence(value: object) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(item for item in value if isinstance(item, Mapping))
    return ()


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


def _catalog(host: Mapping[str, Any]) -> Mapping[str, Any] | None:
    catalog = host.get("catalog")
    return catalog if isinstance(catalog, Mapping) else None


def _host_merge_key(host: Mapping[str, Any], index: int) -> str:
    installation_id = _host_installation_id(host)
    if installation_id is not None:
        return installation_id
    alias = host.get("alias")
    if isinstance(alias, str) and alias.strip():
        return alias.strip()
    return f"remote-{index + 1}"


def _host_installation_id(host: Mapping[str, Any]) -> str | None:
    origin = host.get("origin")
    if isinstance(origin, Mapping):
        value = origin.get("installation_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    for value in (
        host.get("installation_id"),
        host.get("origin_installation_id"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _summary_identity(summary: Mapping[str, Any]) -> tuple[str | None, str | None]:
    logical_key = summary.get("logical_key")
    exact_key = summary.get("exact_key")
    return (
        logical_key if isinstance(logical_key, str) else None,
        exact_key if isinstance(exact_key, str) else None,
    )


def _freshness_value(value: object) -> object:
    if isinstance(value, Mapping):
        return value.get("freshness")
    return value


def _snapshot_identity(host: Mapping[str, Any]) -> tuple[str, str] | None:
    """Return the owner snapshot identity *host*'s page was built from.

    Newer gateways expose a snapshot-specific identity. Older gateways only
    expose the event-store generation; keep accepting that as a conservative
    compatibility identity, but prefer the richer snapshot token whenever it
    exists so age-based rebuilds with unchanged events/counts still reset
    the viewer accumulation.
    """
    catalog = _catalog(host)
    if catalog is None:
        return None
    cursor = catalog.get("snapshot_cursor")
    if not isinstance(cursor, Mapping):
        return None
    for source in (cursor, catalog):
        for key in (
            "snapshot_id",
            "snapshot_identity",
            "snapshot_generation",
            "snapshot_revision",
            "snapshot_token",
        ):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return ("snapshot", value.strip())
            if isinstance(value, int) and not isinstance(value, bool):
                return ("snapshot", str(value))
    generation = cursor.get("store_generation")
    if isinstance(generation, str) and generation:
        return ("store_generation", generation)
    return None


def _snapshot_order(host: Mapping[str, Any]) -> tuple[float, ...] | None:
    """Return best-effort monotonic order evidence for one host snapshot."""
    catalog = _catalog(host) or {}
    cursor = catalog.get("snapshot_cursor")
    cursor_map = cursor if isinstance(cursor, Mapping) else {}
    values: list[float] = []
    for value in (
        catalog.get("snapshot_sequence"),
        cursor_map.get("snapshot_sequence"),
        catalog.get("sequence"),
        cursor_map.get("sequence"),
        host.get("count_revision"),
        host.get("observed_at_unix"),
        host.get("observed_at"),
    ):
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            values.append(float(value))
        elif isinstance(value, str) and value.strip():
            try:
                values.append(float(value))
            except ValueError:
                continue
    return tuple(values) if values else None


def _host_page_merge_mode(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> str:
    first_identity = _snapshot_identity(first)
    second_identity = _snapshot_identity(second)
    if (
        first_identity is None
        or second_identity is None
        or first_identity == second_identity
    ):
        return "union"
    first_order = _snapshot_order(first)
    second_order = _snapshot_order(second)
    if first_order is not None and second_order is not None:
        return "second" if second_order >= first_order else "first"
    return "second"


def _merge_normalized_host_pages(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> dict[str, Any]:
    merge_mode = _host_page_merge_mode(first, second)
    if merge_mode == "first":
        rows = [dict(item) for item in summary_payloads(first)]
        winner = first
    elif merge_mode == "second":
        # A replacement snapshot drops rows and count/cursor evidence absent
        # from that snapshot so vanished rows cannot persist client-side.
        rows = [dict(item) for item in summary_payloads(second)]
        winner = second
    else:
        rows = [dict(item) for item in summary_payloads(first)]
        seen = {_summary_identity(item) for item in rows}
        for item in summary_payloads(second):
            key = _summary_identity(item)
            if key in seen:
                continue
            rows.append(dict(item))
            seen.add(key)
        winner = second

    merged = dict(first)
    if winner is second:
        merged.update(
            {
                key: second[key]
                for key in (
                    "status",
                    "cached",
                    "age_seconds",
                    "partial",
                    "freshness",
                    "observed_at_unix",
                    "authoritative_counts",
                    "count_revision",
                    "catalog",
                    "unresolved_logical_keys",
                )
                if key in second
            }
        )
    merged["summaries"] = rows
    merged["diagnostics"] = [
        *tuple(dict(item) for item in _mapping_sequence(first.get("diagnostics"))),
        *tuple(dict(item) for item in _mapping_sequence(second.get("diagnostics"))),
    ]
    count_input = winner.get("count_input") or first.get("count_input")
    if isinstance(count_input, Mapping):
        merged["count_input"] = {
            **dict(count_input),
            "summaries": rows,
            "authoritative_counts": merged.get("authoritative_counts"),
            "partial": bool(merged.get("partial")),
            "observed_at_unix": merged.get("observed_at_unix"),
            "freshness": _freshness_value(merged.get("freshness"))
            or count_input.get("freshness"),
        }
    return merged
