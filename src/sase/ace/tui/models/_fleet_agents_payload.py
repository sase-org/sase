"""Federation response payload traversal helpers for fleet-agent rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_OK_HOST_STATUSES = frozenset({"ok", "success", "cached"})


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
    direct = _summaries_from_mapping(host)
    if direct:
        return direct
    payload = host.get("payload")
    if isinstance(payload, Mapping):
        page = payload.get("page")
        if isinstance(page, Mapping):
            rows = _mapping_sequence(page.get("rows"))
            if rows:
                return rows
        entries = _mapping_sequence(payload.get("entries"))
        if entries:
            summaries = tuple(
                item["summary"]
                for item in entries
                if isinstance(item.get("summary"), Mapping)
            )
            if summaries:
                return summaries
        nested = _summaries_from_mapping(payload)
        if nested:
            return nested
    result = host.get("result")
    if isinstance(result, Mapping):
        return summary_payloads(result)
    return ()


def _summaries_from_mapping(host: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    for key in ("summaries", "agents", "rows"):
        items = _mapping_sequence(host.get(key))
        if items:
            return items
    return ()


def _mapping_sequence(value: object) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(item for item in value if isinstance(item, Mapping))
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
    diagnostics: list[dict[str, Any]] = []
    raw = response.get("diagnostics")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        diagnostics.extend(dict(item) for item in raw if isinstance(item, Mapping))
    for host in host_payloads(response):
        diagnostics.extend(_diagnostics_from_host(host))
    return tuple(diagnostics)


def response_is_partial(response: Mapping[str, Any] | None) -> bool:
    if response is None:
        return False
    if bool(response.get("partial")):
        return True
    return any(
        _host_is_unhealthy(host) or _host_payload_is_partial(host)
        for host in host_payloads(response)
    )


def authoritative_running_count(response: Mapping[str, Any] | None) -> int | None:
    if response is None:
        return None
    running = 0
    found = False
    for host in host_payloads(response):
        value = _running_from_counts(_counts_mapping(host))
        if value is None:
            continue
        running += value
        found = True
    if found:
        return running
    top = response.get("counts")
    if isinstance(top, Mapping):
        return _running_from_counts(top)
    return None


def catalog_next_cursor(response: Mapping[str, Any] | None) -> str | None:
    if response is None:
        return None
    for host in host_payloads(response):
        page = _catalog_page(host)
        if page is None:
            continue
        if page.get("has_more") is False:
            continue
        cursor = page.get("next_cursor")
        if isinstance(cursor, str) and cursor.strip():
            return cursor.strip()
    return None


def merge_catalog_pages(
    first: Mapping[str, Any] | None,
    second: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if first is None:
        return dict(second) if second is not None else None
    if second is None:
        return dict(first)
    merged_hosts: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for host in (*host_payloads(first), *host_payloads(second)):
        alias = _host_merge_key(host, len(order))
        existing = merged_hosts.get(alias)
        if existing is None:
            merged_hosts[alias] = _with_host_rows(host, summary_payloads(host))
            order.append(alias)
            continue
        merged_hosts[alias] = _merge_host_pages(existing, host)
    merged = dict(first)
    merged["hosts"] = [merged_hosts[alias] for alias in order]
    if second.get("partial") or first.get("partial"):
        merged["partial"] = True
    return merged


def configured_host_count(response: Mapping[str, Any] | None) -> int:
    if response is None:
        return 0
    configured = response.get("configured_hosts")
    if isinstance(configured, int) and configured >= 0:
        return configured
    hosts = host_payloads(response)
    return len(hosts)


def _diagnostics_from_host(host: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    diagnostics: list[dict[str, Any]] = []
    alias = host.get("alias") if isinstance(host.get("alias"), str) else None
    error = host.get("error")
    if isinstance(error, Mapping):
        diagnostics.append(
            {
                "alias": alias,
                "code": error.get("code") or "fleet_host_error",
                "severity": "warning",
                "message": error.get("message") or str(error),
            }
        )
    elif isinstance(error, str) and error.strip():
        diagnostics.append(
            {
                "alias": alias,
                "code": "fleet_host_error",
                "severity": "warning",
                "message": error.strip(),
            }
        )
    elif _host_is_unhealthy(host):
        status = host.get("status")
        diagnostics.append(
            {
                "alias": alias,
                "code": "fleet_host_error",
                "severity": "warning",
                "message": f"host status {status}",
            }
        )
    payload = host.get("payload")
    freshness = payload.get("freshness") if isinstance(payload, Mapping) else None
    if isinstance(freshness, Mapping):
        reason = freshness.get("error")
        if isinstance(reason, str) and reason.strip():
            diagnostics.append(
                {
                    "alias": alias,
                    "code": "fleet_host_stale",
                    "severity": "warning",
                    "message": reason.strip(),
                }
            )
    return tuple(diagnostics)


def _host_is_unhealthy(host: Mapping[str, Any]) -> bool:
    if host.get("error"):
        return True
    status = host.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip().casefold() not in _OK_HOST_STATUSES
    return False


def _host_payload_is_partial(host: Mapping[str, Any]) -> bool:
    payload = host.get("payload")
    if not isinstance(payload, Mapping):
        return False
    freshness = payload.get("freshness")
    if isinstance(freshness, Mapping):
        return bool(freshness.get("partial"))
    return False


def _counts_mapping(host: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = host.get("payload")
    if isinstance(payload, Mapping) and isinstance(payload.get("counts"), Mapping):
        return payload["counts"]
    counts = host.get("counts")
    return counts if isinstance(counts, Mapping) else {}


def _running_from_counts(counts: Mapping[str, Any]) -> int | None:
    running = counts.get("running")
    if isinstance(running, bool):
        return None
    if isinstance(running, int):
        return running
    if isinstance(running, float) and running.is_integer():
        return int(running)
    return None


def _catalog_page(host: Mapping[str, Any]) -> Mapping[str, Any] | None:
    payload = host.get("payload")
    if isinstance(payload, Mapping) and isinstance(payload.get("page"), Mapping):
        return payload["page"]
    page = host.get("page")
    return page if isinstance(page, Mapping) else None


def _host_merge_key(host: Mapping[str, Any], index: int) -> str:
    for value in (
        host.get("alias"),
        host.get("installation_id"),
        host.get("origin_installation_id"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    origin = host.get("origin")
    if isinstance(origin, Mapping):
        for value in (origin.get("alias"), origin.get("installation_id")):
            if isinstance(value, str) and value.strip():
                return value.strip()
    return f"remote-{index + 1}"


def _merge_host_pages(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> dict[str, Any]:
    rows = list(summary_payloads(first))
    seen = {
        (
            item.get("logical_key")
            if isinstance(item.get("logical_key"), str)
            else None,
            item.get("exact_key") if isinstance(item.get("exact_key"), str) else None,
        )
        for item in rows
    }
    for item in summary_payloads(second):
        key = (
            item.get("logical_key")
            if isinstance(item.get("logical_key"), str)
            else None,
            item.get("exact_key") if isinstance(item.get("exact_key"), str) else None,
        )
        if key in seen:
            continue
        rows.append(item)
        seen.add(key)
    merged = _with_host_rows(first, rows)
    second_page = _catalog_page(second)
    payload = merged.get("payload")
    if (
        isinstance(payload, Mapping)
        and isinstance(payload.get("page"), Mapping)
        and isinstance(second_page, Mapping)
    ):
        page = dict(payload["page"])
        if "next_cursor" in second_page:
            page["next_cursor"] = second_page.get("next_cursor")
        if "has_more" in second_page:
            page["has_more"] = second_page.get("has_more")
        payload = dict(payload)
        payload["page"] = page
        merged["payload"] = payload
    if second.get("error"):
        merged["error"] = second.get("error")
        merged["status"] = second.get("status")
    return merged


def _with_host_rows(
    host: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    updated = dict(host)
    payload = updated.get("payload")
    row_list = [dict(item) for item in rows]
    if isinstance(payload, Mapping):
        payload = dict(payload)
        page = payload.get("page")
        if isinstance(page, Mapping):
            page = dict(page)
            page["rows"] = row_list
            payload["page"] = page
        elif _mapping_sequence(payload.get("entries")):
            payload["entries"] = [
                {"schema_version": 1, "summary": dict(item)} for item in row_list
            ]
        else:
            payload["rows"] = row_list
        updated["payload"] = payload
        if "summaries" in updated:
            updated["summaries"] = row_list
        return updated
    updated["summaries"] = row_list
    return updated
