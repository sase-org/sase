"""Presentation-neutral usage-window projections for integrations."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from typing import Any

from sase.integrations._usage_windows_models import (
    UsageProviderRow as UsageProviderRow,
    UsageWindowRow as UsageWindowRow,
    UsageWindowsRefresh as UsageWindowsRefresh,
    UsageWindowsReport as UsageWindowsReport,
)
from sase.integrations.provider_badges import provider_emoji_badge
from sase.llm_provider.usage._refresh_model import (
    USAGE_REFRESH_BATCH_DEADLINE_SECONDS,
)

USAGE_WINDOWS_REFRESH_TIMEOUT_SECONDS: float = (
    USAGE_REFRESH_BATCH_DEADLINE_SECONDS + 30.0
)

_SELECT_EVERYTHING_INDICATOR: dict[str, object] = {
    "enabled": True,
    "default": "always",
    "weekly_all": "always",
}

__all__ = [
    "USAGE_WINDOWS_REFRESH_TIMEOUT_SECONDS",
    "UsageProviderRow",
    "UsageWindowRow",
    "UsageWindowsRefresh",
    "UsageWindowsReport",
    "live_usage_refresh_operations",
    "request_usage_windows_refresh",
    "resolve_usage_provider",
    "usage_windows_report",
]


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _nonblank_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _probe_floors_guarded() -> dict[str, float]:
    try:
        from sase.llm_provider.usage._probe_meta import usage_probe_floors

        return dict(usage_probe_floors())
    except Exception:
        return {}


def _eligible_guarded() -> tuple[str, ...]:
    try:
        from sase.llm_provider.usage.refresh import eligible_usage_providers

        return tuple(eligible_usage_providers())
    except Exception:
        return ()


def _alias_map_guarded() -> dict[str, str]:
    try:
        from sase.llm_provider.registry import model_short_alias_map

        result = model_short_alias_map()
        return dict(result) if isinstance(result, dict) else {}
    except Exception:
        return {}


def _display_names_guarded() -> dict[str, str]:
    try:
        from sase.llm_provider.registry import get_llm_metadata_payload

        payload = get_llm_metadata_payload()
        providers = payload.get("providers") if isinstance(payload, dict) else None
        if not isinstance(providers, dict):
            return {}
        names: dict[str, str] = {}
        for key, metadata in providers.items():
            if not isinstance(key, str) or not isinstance(metadata, dict):
                continue
            display = metadata.get("display_name")
            if isinstance(display, str) and display.strip():
                names[key] = display.strip()
        return names
    except Exception:
        return {}


def _registered_names_guarded() -> tuple[str, ...]:
    try:
        from sase.llm_provider.registry import registered_provider_names

        return tuple(registered_provider_names())
    except Exception:
        return ()


def _snapshot_provider_rows(
    snapshot: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    raw = snapshot.get("providers")
    if not isinstance(raw, list):
        return {}
    rows: dict[str, Mapping[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        name = item.get("provider")
        if isinstance(name, str) and name and name not in rows:
            rows[name] = item
    return rows


def _window_key(entry: Mapping[str, Any], fallback: str) -> str:
    key = entry.get("window_key")
    if isinstance(key, str) and key:
        return key
    key = entry.get("key")
    if isinstance(key, str) and key:
        return key
    return fallback


# symvision: https://github.com/sase-org/sase-telegram.git
def usage_windows_report(
    providers: Sequence[str] = (),
    *,
    now: float | None = None,
) -> UsageWindowsReport:
    """Return every usage window for configured providers."""
    from sase.llm_provider.usage.config import get_usage_metrics_settings
    from sase.llm_provider.usage.presentation import (
        collector_retry_label,
        provider_status_label,
    )
    from sase.llm_provider.usage.store import (
        load_provider_usage,
        provider_usage_format_remaining_text,
        provider_usage_project_indicator,
    )

    clock = time.time() if now is None else float(now)
    settings = get_usage_metrics_settings()
    eligible = tuple(sorted(_eligible_guarded()))
    requested = tuple(
        dict.fromkeys(str(name).strip() for name in providers if str(name).strip())
    )
    if not settings.enabled:
        return UsageWindowsReport(
            generated_at=clock,
            collection_enabled=False,
            providers=(),
            configured_providers=eligible,
            diagnostics=(),
        )
    read = load_provider_usage(
        now=clock,
        cadence_seconds=settings.refresh_seconds,
        warn_percent=settings.warn_percent,
        critical_percent=settings.critical_percent,
    )
    snapshot = read.snapshot
    eligible_union = sorted(set(eligible) | set(requested))
    floors = _probe_floors_guarded()
    projection = provider_usage_project_indicator(
        snapshot,
        indicator=dict(_SELECT_EVERYTHING_INDICATOR),
        eligible_providers=eligible_union,
        now=clock,
        cadence_seconds=settings.refresh_seconds,
        warn_percent=settings.warn_percent,
        critical_percent=settings.critical_percent,
        provider_min_intervals=floors,
    )
    entries_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for entry in projection.entries:
        if not isinstance(entry, Mapping):
            continue
        provider = entry.get("provider")
        if not isinstance(provider, str) or not provider:
            continue
        key = _window_key(entry, "")
        if not key:
            continue
        entries_by_key.setdefault((provider, key), entry)
    snapshot_rows = _snapshot_provider_rows(snapshot)
    alias_map = _alias_map_guarded()
    display_names = _display_names_guarded()
    if requested:
        target_providers = sorted(set(requested))
    else:
        target_providers = sorted(set(eligible))
    provider_rows: list[UsageProviderRow] = []
    for key in target_providers:
        row = snapshot_rows.get(key)
        if row is None:
            synthetic: dict[str, Any] = {
                "provider": key,
                "collection_status": "no_observations",
                "collection_reason": "not_cached",
                "windows": [],
            }
            provider_rows.append(
                _build_provider_row(
                    key,
                    synthetic,
                    (),
                    clock,
                    display_names,
                    provider_status_label,
                    collector_retry_label,
                )
            )
            continue
        windows = _build_window_rows(
            key,
            row,
            entries_by_key,
            clock,
            alias_map,
            provider_usage_format_remaining_text,
        )
        provider_rows.append(
            _build_provider_row(
                key,
                row,
                windows,
                clock,
                display_names,
                provider_status_label,
                collector_retry_label,
            )
        )
    generated = _finite_number(snapshot.get("generated_at"))
    diagnostics: list[str] = []
    for store_item in read.diagnostics:
        provider = getattr(store_item, "provider", None)
        message = getattr(store_item, "message", "")
        label = provider if isinstance(provider, str) and provider else "store"
        diagnostics.append(f"{label}: {message}")
    for indicator_item in projection.diagnostics:
        path = getattr(indicator_item, "path", "")
        message = getattr(indicator_item, "message", "")
        diagnostics.append(f"{path}: {message}")
    return UsageWindowsReport(
        generated_at=generated if generated is not None else clock,
        collection_enabled=True,
        providers=tuple(provider_rows),
        configured_providers=eligible,
        diagnostics=tuple(diagnostics),
    )


def _build_provider_row(
    key: str,
    row: Mapping[str, Any],
    windows: tuple[UsageWindowRow, ...],
    now: float,
    display_names: Mapping[str, str],
    provider_status_label: Any,
    collector_retry_label: Any,
) -> UsageProviderRow:
    display_name = display_names.get(key)
    if not isinstance(display_name, str) or not display_name:
        fallback = _nonblank_text(row.get("display_name"))
        display_name = fallback or key
    plan_text = _nonblank_text(row.get("plan"))
    status = str(row.get("collection_status") or "unknown")
    try:
        status_label = str(provider_status_label(row))
    except Exception:
        status_label = status.replace("_", " ")
    health = row.get("collector_health")
    health_map = health if isinstance(health, Mapping) else None
    collector_state: str | None = None
    if health_map is not None:
        raw_state = health_map.get("state")
        if isinstance(raw_state, str) and raw_state:
            collector_state = raw_state
    try:
        retry_label = collector_retry_label(health_map, now)
    except Exception:
        retry_label = None
    if not isinstance(retry_label, str):
        retry_label = None
    last_observed: float | None = _finite_number(row.get("last_full_observation_at"))
    if last_observed is None:
        last_observed = _finite_number(row.get("last_attempt_at"))
    return UsageProviderRow(
        provider=key,
        display_name=display_name,
        emoji=provider_emoji_badge(key),
        plan=plan_text,
        collection_status=status,
        status_label=status_label,
        collector_state=collector_state,
        retry_label=retry_label,
        last_observed_at=last_observed,
        windows=windows,
    )


def _build_window_rows(
    provider: str,
    row: Mapping[str, Any],
    entries_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    now: float,
    alias_map: Mapping[str, str],
    format_remaining_text: Any,
) -> tuple[UsageWindowRow, ...]:
    raw_windows = row.get("windows")
    if not isinstance(raw_windows, list):
        return ()
    built: list[UsageWindowRow] = []
    for window in raw_windows:
        if not isinstance(window, Mapping):
            continue
        snapshot_key = str(window.get("key") or window.get("window_key") or "")
        if not snapshot_key:
            continue
        entry = entries_by_key.get((provider, snapshot_key))
        built.append(
            _build_window_row(
                snapshot_key,
                window,
                entry,
                now,
                alias_map,
                format_remaining_text,
            )
        )
    return tuple(built)


def _build_window_row(
    snapshot_key: str,
    window: Mapping[str, Any],
    entry: Mapping[str, Any] | None,
    now: float,
    alias_map: Mapping[str, str],
    format_remaining_text: Any,
) -> UsageWindowRow:
    label = _nonblank_text(window.get("label")) or snapshot_key
    period_kind = "unknown"
    duration_seconds: float | None = None
    scope_kind = "unknown"
    scope_family: str | None = None
    scope_model_ids: list[str] = []
    scope_vendor_label: str | None = None
    used: float | None = None
    remaining: float | None = None
    exceeded: float | None = _finite_number(window.get("exceeded_by_percent"))
    resets_at: float | None = _finite_number(window.get("resets_at"))
    reset_state = "unknown"
    seconds_until_reset: float | None = None
    freshness = str(window.get("freshness") or "unknown")
    age = _finite_number(window.get("age_seconds"))
    vendor_state = str(window.get("vendor_state") or "unknown")
    attention = "none"
    if entry is not None:
        period = entry.get("period")
        if isinstance(period, Mapping):
            raw_kind = period.get("kind")
            if isinstance(raw_kind, str) and raw_kind:
                period_kind = raw_kind
            duration_seconds = _finite_number(period.get("duration_seconds"))
        scope = entry.get("scope")
        if isinstance(scope, Mapping):
            raw_scope = scope.get("kind")
            if isinstance(raw_scope, str) and raw_scope:
                scope_kind = raw_scope
            family = scope.get("family")
            if isinstance(family, str) and family.strip():
                scope_family = family.strip()
            model_ids = scope.get("model_ids")
            if isinstance(model_ids, list):
                scope_model_ids = [
                    str(item) for item in model_ids if isinstance(item, str) and item
                ]
            vendor_label = scope.get("vendor_label")
            if isinstance(vendor_label, str) and vendor_label.strip():
                scope_vendor_label = vendor_label.strip()
        used = _finite_number(entry.get("used_percent"))
        remaining = _finite_number(entry.get("remaining_percent"))
        entry_exceeded = _finite_number(entry.get("exceeded_by_percent"))
        if entry_exceeded is not None:
            exceeded = entry_exceeded
        resets_at = _finite_number(entry.get("resets_at"))
        raw_reset = entry.get("reset_state")
        if isinstance(raw_reset, str) and raw_reset:
            reset_state = raw_reset
        seconds_until_reset = _finite_number(entry.get("seconds_until_reset"))
        raw_freshness = entry.get("freshness")
        if isinstance(raw_freshness, str) and raw_freshness:
            freshness = raw_freshness
        entry_age = _finite_number(entry.get("age_seconds"))
        if entry_age is not None:
            age = entry_age
        raw_vendor = entry.get("vendor_state")
        if isinstance(raw_vendor, str) and raw_vendor:
            vendor_state = raw_vendor
        raw_attention = entry.get("display_attention")
        if not isinstance(raw_attention, str) or not raw_attention:
            raw_attention = entry.get("window_attention")
        if not isinstance(raw_attention, str) or not raw_attention:
            raw_attention = entry.get("attention")
        if isinstance(raw_attention, str) and raw_attention:
            attention = raw_attention
    if used is None:
        used = _finite_number(window.get("used_percent"))
    if used is None and remaining is not None:
        used = max(0.0, 100.0 - remaining)
    if used is None:
        used = 0.0
    if remaining is None:
        remaining = _finite_number(window.get("remaining_percent"))
    if remaining is None:
        remaining = max(0.0, min(100.0, 100.0 - used))
    remaining = max(0.0, min(100.0, remaining))
    try:
        remaining_text = str(format_remaining_text(float(used)))
    except Exception:
        remaining_text = f"{remaining:g}% left"
    scope_models = tuple(
        dict.fromkeys(alias_map.get(model_id, model_id) for model_id in scope_model_ids)
    )
    return UsageWindowRow(
        key=snapshot_key,
        label=label,
        period=period_kind,
        duration_seconds=duration_seconds,
        scope=scope_kind,
        scope_family=scope_family,
        scope_models=scope_models,
        scope_vendor_label=scope_vendor_label,
        used_percent=float(used),
        remaining_percent=float(remaining),
        remaining_text=remaining_text,
        exceeded_by_percent=exceeded,
        resets_at=resets_at,
        reset_state=reset_state,
        seconds_until_reset=seconds_until_reset,
        freshness=freshness,
        age_seconds=float(age) if age is not None else 0.0,
        vendor_state=vendor_state,
        attention=attention,
    )


# symvision: https://github.com/sase-org/sase-telegram.git
def resolve_usage_provider(name: str) -> str | None:
    """Return the provider key matching a key or display name."""
    needle = name.strip().lower() if isinstance(name, str) else ""
    if not needle:
        return None
    registered = _registered_names_guarded()
    if not registered:
        return None
    display_names = _display_names_guarded()
    for key in registered:
        if key.lower() == needle:
            return key
    for key in registered:
        display = display_names.get(key, "")
        if isinstance(display, str) and display.strip().lower() == needle:
            return key
    return None


# symvision: https://github.com/sase-org/sase-telegram.git
def request_usage_windows_refresh(
    providers: Sequence[str] = (),
) -> UsageWindowsRefresh:
    """Submit an explicit chat-origin refresh and summarize the receipt."""
    from sase.llm_provider.usage.presentation import render_usage_refresh_toast
    from sase.llm_provider.usage.refresh import submit_usage_refresh

    requested = tuple(
        dict.fromkeys(str(name).strip() for name in providers if str(name).strip())
    )
    receipt = submit_usage_refresh(requested or None, explicit=True, origin="chat")
    try:
        summary = str(render_usage_refresh_toast(receipt))
    except Exception:
        summary = "Usage refresh submitted"
    started_providers = tuple(
        str(item.provider)
        for item in getattr(receipt, "providers", ())
        if getattr(item, "operation_id", None)
        and isinstance(getattr(item, "provider", None), str)
    )
    return UsageWindowsRefresh(
        started=bool(getattr(receipt, "operation_ids", ())),
        operation_ids=tuple(getattr(receipt, "operation_ids", ())),
        providers=started_providers,
        summary=summary,
    )


# symvision: https://github.com/sase-org/sase-telegram.git
def live_usage_refresh_operations(
    operation_ids: Sequence[str],
) -> frozenset[str]:
    """Return the subset of ids with a live refresh reservation."""
    pending = frozenset(str(item) for item in operation_ids if str(item))
    if not pending:
        return frozenset()
    try:
        from sase.llm_provider.usage.store import (
            list_provider_usage_refresh_reservations,
        )

        reservations = list_provider_usage_refresh_reservations()
    except Exception:
        return pending
    try:
        live = frozenset(
            str(item.operation_id)
            for item in reservations
            if str(getattr(item, "operation_id", "")) in pending
        )
    except Exception:
        return pending
    return live & pending
