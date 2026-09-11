"""Fleet federation response builders for offline TUI fixtures."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from hashlib import sha256
from typing import Any

from tests.ace.tui._fleet_locator_fixture import fleet_installation_id
from tests.ace.tui._fleet_summary_fixture import _connection_health, _freshness


def fleet_host_response(
    *,
    alias: str = "apollo",
    installation_id: str | None = None,
    summaries: Iterable[Mapping[str, Any]] | None = None,
    freshness: str = "fresh",
    connection_health: str = "online",
    observed_at_unix: float | None = 1_800_000_000.0,
    counts: Mapping[str, Any] | None = None,
    diagnostics: Iterable[Mapping[str, Any]] = (),
    partial: bool = False,
    operation: str = "catalog",
) -> dict[str, Any]:
    """Build a federation read response containing one host."""
    origin_id = installation_id or fleet_installation_id()
    summary_list = [
        _summary_with_host_observation(
            dict(summary),
            freshness=freshness,
            connection_health=connection_health,
            observed_at_unix=observed_at_unix,
        )
        for summary in summaries or ()
    ]
    host_counts = (
        dict(counts)
        if counts is not None
        else fleet_counts(summary_list, observed_at_unix=observed_at_unix)
    )
    response: dict[str, Any] = {
        "schema_version": 1,
        "operation": operation,
        "configured_hosts": 1,
        "hosts": [
            {
                "schema_version": 1,
                "alias": alias,
                "provider_ref": f"{alias}-provider",
                "installation_id": origin_id,
                "endpoint": f"https://{alias}.example.test",
                "status": "ok",
                "cached": _freshness(freshness) != "fresh",
                "age_seconds": None,
                "payload": {
                    "schema_version": 1,
                    "cursor": _store_cursor(alias),
                    "counts": host_counts,
                    "count_revision": _max_revision(summary_list),
                    "freshness": _freshness_wire(
                        freshness,
                        observed_at_unix=observed_at_unix,
                        partial=partial,
                    ),
                    "page": {
                        "schema_version": 1,
                        "snapshot_id": fleet_catalog_snapshot_id(alias),
                        "rows": summary_list,
                        "limit": 100,
                        "total_matching_rows": host_counts["logical_agent_total"],
                        "next_cursor": None,
                        "has_more": False,
                    },
                },
                "error": None,
            }
        ],
    }
    diagnostic_list = [
        _diagnostic(diagnostic, operation=operation) for diagnostic in diagnostics
    ]
    if diagnostic_list:
        response["diagnostics"] = diagnostic_list
    if partial:
        response["partial"] = True
    return response


def fleet_host_payload(
    *,
    alias: str = "apollo",
    installation_id: str | None = None,
    summaries: Iterable[Mapping[str, Any]] | None = None,
    freshness: str = "fresh",
    connection_health: str = "online",
    observed_at_unix: float | None = 1_800_000_000.0,
    counts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one host payload for a multi-host federation response."""
    return dict(
        fleet_host_response(
            alias=alias,
            installation_id=installation_id,
            summaries=summaries,
            freshness=freshness,
            connection_health=connection_health,
            observed_at_unix=observed_at_unix,
            counts=counts,
        )["hosts"][0]
    )


def fleet_multi_host_response(
    *hosts: Mapping[str, Any],
    configured_hosts: int | None = None,
    diagnostics: Iterable[Mapping[str, Any]] = (),
    partial: bool = False,
) -> dict[str, Any]:
    """Build a deterministic federation response spanning multiple hosts."""
    host_list = [copy.deepcopy(dict(host)) for host in hosts]
    response: dict[str, Any] = {
        "schema_version": 1,
        "operation": "catalog",
        "configured_hosts": configured_hosts
        if configured_hosts is not None
        else len(host_list),
        "hosts": host_list,
    }
    diagnostic_list = [
        _diagnostic(diagnostic, operation="catalog") for diagnostic in diagnostics
    ]
    if diagnostic_list:
        response["diagnostics"] = diagnostic_list
    if partial:
        response["partial"] = True
    return response


def fleet_fault_diagnostic(
    *,
    alias: str,
    operation: str,
    code: str,
    message: str,
    severity: str = "warning",
) -> dict[str, Any]:
    """Build a host-scoped fault diagnostic for offline Fleet tests."""
    return {
        "schema_version": 1,
        "alias": alias,
        "operation": operation,
        "code": code,
        "severity": severity,
        "message": message,
    }


def _summary_payloads(host: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    payload = host.get("payload")
    if isinstance(payload, Mapping):
        page = payload.get("page")
        if isinstance(page, Mapping):
            rows = page.get("rows")
            if isinstance(rows, Iterable) and not isinstance(
                rows,
                (str, bytes, bytearray),
            ):
                return tuple(item for item in rows if isinstance(item, Mapping))
    return ()


def fleet_counts(
    summaries: Iterable[Mapping[str, Any]],
    *,
    running: int | None = None,
    observed_at_unix: float | None = None,
) -> dict[str, Any]:
    """Build valid authoritative logical-agent counts for fixture summaries."""
    summary_list = list(summaries)
    total = len(summary_list)
    max_revision = _max_revision(summary_list)
    observed = (
        observed_at_unix
        if observed_at_unix is not None
        else _max_observed_at_unix(summary_list)
    )
    running_count = (
        running
        if running is not None
        else sum(1 for summary in summary_list if _summary_counts_as_running(summary))
    )
    attention_count = sum(
        1 for summary in summary_list if summary.get("needs_attention")
    )
    waiting_count = sum(
        1
        for summary in summary_list
        if str(summary.get("status_bucket") or "").casefold()
        in {"waiting", "queued", "stopped"}
    )
    occupied_count = (
        running_count
        if running is not None
        else sum(
            1 for summary in summary_list if bool(summary.get("occupied_runner_slot"))
        )
    )
    return {
        "schema_version": 1,
        "basis": {
            "schema_version": 1,
            "input_rows": total,
            "selected_rows": total,
            "max_revision": max_revision,
            "observed_at_unix_max": observed,
        },
        "logical_agent_total": total,
        "running": running_count,
        "waiting": waiting_count,
        "attention": attention_count,
        "occupied_runner_slots": occupied_count,
    }


def fleet_catalog_snapshot_id(seed: str) -> str:
    """Build a valid fleet catalog snapshot id for test payloads."""
    return f"catsnap_v1_{sha256(seed.encode()).hexdigest()}"


def fleet_catalog_cursor(snapshot_id: str, offset: int) -> str:
    """Build a valid presentation catalog continuation cursor."""
    return f"catcur_v1:p:{snapshot_id}:{offset}"


def fleet_attention_response(
    entries: Iterable[Mapping[str, Any]],
    *,
    alias: str = "apollo",
) -> dict[str, Any]:
    """Build a federation attention response for logical-key lookups."""
    return {
        "schema_version": 1,
        "configured_hosts": 1,
        "hosts": [
            {
                "schema_version": 1,
                "alias": alias,
                "payload": {"entries": [dict(entry) for entry in entries]},
            }
        ],
    }


def _store_cursor(alias: str) -> dict[str, Any]:
    safe_alias = "".join(
        character if character.isalnum() or character in "_-" else "_"
        for character in alias
    )
    return {
        "schema_version": 1,
        "store_generation": f"gen-{safe_alias or 'fleet'}",
        "sequence": 1,
    }


def _freshness_wire(
    value: str,
    *,
    observed_at_unix: float | None,
    partial: bool,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "freshness": _freshness(value),
        "partial": partial,
        "refreshed_at_unix": observed_at_unix,
        "error": "partial" if partial else None,
    }


def _summary_with_host_observation(
    summary: dict[str, Any],
    *,
    freshness: str,
    connection_health: str,
    observed_at_unix: float | None,
) -> dict[str, Any]:
    summary["freshness"] = _freshness(freshness)
    summary["connection_health"] = _connection_health(connection_health)
    if observed_at_unix is not None:
        summary["observed_at_unix"] = observed_at_unix
    return summary


def _max_revision(summaries: Iterable[Mapping[str, Any]]) -> int | None:
    revisions: list[int] = []
    for summary in summaries:
        revision = summary.get("row_revision")
        if isinstance(revision, Mapping):
            value = revision.get("revision")
            if isinstance(value, int) and not isinstance(value, bool):
                revisions.append(value)
    return max(revisions) if revisions else None


def _max_observed_at_unix(summaries: Iterable[Mapping[str, Any]]) -> float | None:
    values: list[float] = []
    for summary in summaries:
        value = summary.get("observed_at_unix")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return max(values) if values else None


def _summary_counts_as_running(summary: Mapping[str, Any]) -> bool:
    if bool(summary.get("dismissable")):
        return False
    return str(summary.get("status_bucket") or "").casefold() == "running"


def _diagnostic(diagnostic: Mapping[str, Any], *, operation: str) -> dict[str, Any]:
    value = dict(diagnostic)
    value.setdefault("schema_version", 1)
    value.setdefault("alias", None)
    value.setdefault("operation", operation)
    return value
