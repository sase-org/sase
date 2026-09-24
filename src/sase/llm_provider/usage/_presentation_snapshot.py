"""Stable JSON payload and provider-row filtering for usage presentation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.llm_provider.usage.store import ProviderUsageStoreDiagnostic


def _provider_rows(snapshot: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = snapshot.get("providers")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def usage_snapshot_json_payload(
    snapshot: Mapping[str, Any],
    diagnostics: Sequence[ProviderUsageStoreDiagnostic | Mapping[str, Any]] = (),
    *,
    requested_providers: Sequence[str] = (),
) -> dict[str, Any]:
    """Return the stable JSON payload emitted by ``sase usage list``."""
    payload = _filtered_usage_snapshot(snapshot, requested_providers)
    payload["requested_providers"] = list(requested_providers)
    payload["missing_providers"] = list(
        _missing_usage_providers(snapshot, requested_providers)
    )
    payload["store_diagnostics"] = [
        usage_diagnostic_to_json(item) for item in diagnostics
    ]
    return payload


def _filtered_usage_snapshot(
    snapshot: Mapping[str, Any],
    requested_providers: Sequence[str] = (),
) -> dict[str, Any]:
    """Copy *snapshot* and filter provider rows without mutating the input."""
    payload = dict(snapshot)
    provider_filter = set(requested_providers)
    providers = [
        dict(item)
        for item in _provider_rows(snapshot)
        if not provider_filter or str(item.get("provider") or "") in provider_filter
    ]
    payload["providers"] = providers
    if provider_filter:
        payload["collection_health"] = _filtered_collection_health(providers)
    return payload


def _missing_usage_providers(
    snapshot: Mapping[str, Any],
    requested_providers: Sequence[str],
) -> tuple[str, ...]:
    """Return requested providers absent from the cached public snapshot."""
    if not requested_providers:
        return ()
    observed = {str(item.get("provider") or "") for item in _provider_rows(snapshot)}
    return tuple(name for name in requested_providers if name not in observed)


def usage_diagnostic_to_json(
    diagnostic: ProviderUsageStoreDiagnostic | Mapping[str, Any],
) -> dict[str, Any]:
    """Return a JSON-ready store diagnostic."""
    if isinstance(diagnostic, Mapping):
        return {
            "provider": diagnostic.get("provider"),
            "message": str(diagnostic.get("message") or ""),
        }
    return {"provider": diagnostic.provider, "message": diagnostic.message}


def display_provider_rows(
    snapshot: Mapping[str, Any],
    requested_providers: Sequence[str],
) -> tuple[Mapping[str, Any], ...]:
    provider_filter = set(requested_providers)
    rows = [
        dict(item)
        for item in _provider_rows(snapshot)
        if not provider_filter or str(item.get("provider") or "") in provider_filter
    ]
    for provider in _missing_usage_providers(snapshot, requested_providers):
        rows.append(
            {
                "provider": provider,
                "collection_status": "no_observations",
                "collection_reason": "not_cached",
                "windows": [],
            }
        )
    return tuple(rows)


def _filtered_collection_health(providers: Sequence[Mapping[str, Any]]) -> str:
    if not providers:
        return "empty"
    statuses = {str(item.get("collection_status") or "") for item in providers}
    if statuses <= {"ok"}:
        return "ok"
    if "ok" in statuses:
        return "partial"
    return "error"
