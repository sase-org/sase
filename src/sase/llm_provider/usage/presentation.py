"""Shared presentation helpers for cached subscription usage."""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any

from sase.core.time import format_local
from sase.llm_provider.usage.store import (
    ProviderUsageStoreDiagnostic,
    provider_usage_format_remaining_text,
)

_PLAIN_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:/@+=%-]+$")
_STATE_STATUS_LABELS: Mapping[str, str] = {
    "ok": "ok",
    "error": "error",
    "unsupported": "unsupported",
    "unauthenticated": "logged out",
    "not_applicable": "not applicable",
    "no_observations": "no observations",
    "disabled": "disabled",
    "deferred": "deferred",
}
_WINDOW_STATE_LABELS: Mapping[str, str] = {
    "allowed": "ok",
    "warning": "warning",
    "rejected": "exhausted",
    "unknown": "unknown",
}
_ATTENTION_STYLES: Mapping[str, str] = {
    "rejected": "bold red",
    "very_low": "bold red",
    "low": "yellow",
    "collection_problem": "yellow",
}
_COLLECTOR_HEALTH_STYLES: Mapping[str, str] = {
    "degraded": "yellow",
    "failing": "bold #FFAF5F",
}


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
        _usage_diagnostic_to_json(item) for item in diagnostics
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


def render_usage_plain(
    snapshot: Mapping[str, Any],
    diagnostics: Sequence[ProviderUsageStoreDiagnostic | Mapping[str, Any]] = (),
    *,
    requested_providers: Sequence[str] = (),
    verbose: bool = False,
    now: float | None = None,
) -> str:
    """Render cached usage as undecorated, line-oriented ASCII text."""
    clock = time.time() if now is None else float(now)
    rows = list(_display_provider_rows(snapshot, requested_providers))
    lines = ["Subscription usage"]
    if not rows:
        lines.append("No observations yet; run sase usage refresh.")
    for provider in rows:
        windows = _window_rows(provider)
        if not windows:
            lines.append(_provider_plain_record(provider, verbose=verbose, now=clock))
            continue
        lines.append(_provider_plain_record(provider, verbose=verbose, now=clock))
        for window in windows:
            lines.append(
                _window_plain_record(
                    str(provider.get("provider") or ""),
                    window,
                    verbose=verbose,
                    now=clock,
                )
            )
    for item in diagnostics:
        diagnostic = _usage_diagnostic_to_json(item)
        lines.append(
            _plain_record(
                "diagnostic",
                provider=diagnostic.get("provider") or "store",
                message=diagnostic.get("message") or "",
            )
        )
    return "\n".join(lines)


def render_usage_rich(
    snapshot: Mapping[str, Any],
    diagnostics: Sequence[ProviderUsageStoreDiagnostic | Mapping[str, Any]] = (),
    *,
    requested_providers: Sequence[str] = (),
    verbose: bool = False,
    now: float | None = None,
) -> object:
    """Return a Rich renderable for cached usage."""
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    clock = time.time() if now is None else float(now)
    rows = list(_display_provider_rows(snapshot, requested_providers))
    if not rows:
        return Panel(
            Text("No observations yet; run sase usage refresh."),
            title="Subscription usage",
        )

    table = Table(title="Subscription usage", expand=True)
    table.add_column("Provider", no_wrap=True)
    table.add_column("Remaining", justify="right", no_wrap=True)
    table.add_column("Window")
    table.add_column("Reset", no_wrap=True)
    table.add_column("Age", justify="right", no_wrap=True)
    table.add_column("Status")
    if verbose:
        table.add_column("Source")

    for provider in rows:
        windows = _window_rows(provider)
        if not windows:
            values = [
                str(provider.get("provider") or "-"),
                "-",
                "-",
                "-",
                _age_from_timestamp(provider.get("last_attempt_at"), clock),
                provider_status_label(provider),
            ]
            if verbose:
                values.append(_optional_text(provider.get("diagnostic")) or "-")
            table.add_row(*values, style=provider_style(provider))
            continue
        for index, window in enumerate(windows):
            provider_label = str(provider.get("provider") or "-") if index == 0 else ""
            values = [
                provider_label,
                _remaining_label(window),
                window_label(window),
                reset_label(window, clock, verbose=verbose),
                age_label(window),
                _window_status_label_for_provider(provider, window),
            ]
            if verbose:
                values.append(_window_source_label(window))
            table.add_row(*values, style=_provider_window_style(provider, window))

    diagnostic_lines = tuple(
        diagnostic_line(_usage_diagnostic_to_json(item)) for item in diagnostics
    )
    if diagnostic_lines:
        return Group(table, Text("\n".join(diagnostic_lines), style="yellow"))
    return table


def render_refresh_receipt_plain(receipt: Any) -> str:
    """Render a refresh receipt as line-oriented ASCII text."""
    operation_ids = tuple(str(item) for item in getattr(receipt, "operation_ids", ()))
    lines = ["Usage refresh"]
    if operation_ids:
        lines.append(
            _plain_record(
                "batch",
                status="submitted",
                operations=",".join(operation_ids),
                origin=getattr(receipt, "origin", ""),
            )
        )
    else:
        lines.append(
            _plain_record(
                "batch",
                status="not_started",
                origin=getattr(receipt, "origin", ""),
            )
        )
    for item in getattr(receipt, "providers", ()):
        lines.append(
            _plain_record(
                "provider",
                provider=getattr(item, "provider", ""),
                status=getattr(item, "status", ""),
                reason=getattr(item, "reason", None),
                operation=getattr(item, "operation_id", None),
            )
        )
    return "\n".join(lines)


def _usage_diagnostic_to_json(
    diagnostic: ProviderUsageStoreDiagnostic | Mapping[str, Any],
) -> dict[str, Any]:
    """Return a JSON-ready store diagnostic."""
    if isinstance(diagnostic, Mapping):
        return {
            "provider": diagnostic.get("provider"),
            "message": str(diagnostic.get("message") or ""),
        }
    return {"provider": diagnostic.provider, "message": diagnostic.message}


def _provider_rows(snapshot: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = snapshot.get("providers")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _window_rows(provider: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = provider.get("windows")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _display_provider_rows(
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


def _provider_plain_record(
    provider: Mapping[str, Any],
    *,
    verbose: bool,
    now: float,
) -> str:
    values: dict[str, Any] = {
        "provider": provider.get("provider") or "",
        "status": provider.get("collection_status") or "unknown",
    }
    summary = provider.get("summary")
    if isinstance(summary, Mapping):
        used = _number(summary.get("used_percent"))
        if used is not None:
            values["remaining"] = provider_usage_format_remaining_text(used)
            values["used_percent"] = _format_number(used)
        freshness = _optional_text(summary.get("freshness"))
        if freshness is not None:
            values["freshness"] = freshness
    reason = _optional_text(provider.get("collection_reason"))
    if reason is not None:
        values["reason"] = reason
    diagnostic = _optional_text(provider.get("diagnostic"))
    if diagnostic is not None:
        values["diagnostic"] = diagnostic
    if verbose:
        health = _provider_collector_health(provider)
        if health is not None:
            values["health"] = str(health.get("state") or "unknown")
            failures = _failure_count(health)
            if failures is not None:
                values["consecutive_failures"] = failures
            values["last_success"] = timestamp_label(health.get("last_success_at"), now)
            values["failing_since"] = timestamp_label(health.get("failing_since"), now)
        values["plan"] = provider.get("plan")
        values["account_mode"] = provider.get("account_mode")
        values["last_attempt"] = timestamp_label(provider.get("last_attempt_at"), now)
        values["last_full_observation"] = timestamp_label(
            provider.get("last_full_observation_at"), now
        )
    return _plain_record("provider", **values)


def _window_plain_record(
    provider: str,
    window: Mapping[str, Any],
    *,
    verbose: bool,
    now: float,
) -> str:
    used = _number(window.get("used_percent"))
    values: dict[str, Any] = {
        "provider": provider,
        "key": window.get("key") or "",
        "label": window.get("label") or window.get("key") or "",
        "remaining": "-"
        if used is None
        else provider_usage_format_remaining_text(used),
        "used_percent": "-" if used is None else _format_number(used),
        "reset": reset_label(window, now, verbose=False),
        "age": age_label(window),
        "freshness": window.get("freshness") or "unknown",
        "state": window.get("vendor_state") or "unknown",
        "source": window.get("source") or "unknown",
        "scope": applicability_label(window.get("applicability")),
    }
    if verbose:
        values["observed_at"] = timestamp_label(window.get("observed_at"), now)
        values["resets_at"] = timestamp_label(window.get("resets_at"), now)
        exceeded = _number(window.get("exceeded_by_percent"))
        if exceeded is not None:
            values["exceeded_by_percent"] = _format_number(exceeded)
    return _plain_record("window", **values)


def _plain_record(kind: str, **values: Any) -> str:
    fields = [
        f"{name}={_plain_value(value)}"
        for name, value in values.items()
        if value is not None and value != ""
    ]
    return " ".join((kind, *fields))


def _plain_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return _format_number(float(value))
    text = str(value)
    if _PLAIN_TOKEN_RE.fullmatch(text):
        return text
    return json.dumps(text, ensure_ascii=True)


def provider_status_label(provider: Mapping[str, Any]) -> str:
    health_label = _unhealthy_collector_health_label(provider)
    if health_label is not None:
        return health_label
    status = str(provider.get("collection_status") or "unknown")
    label = _STATE_STATUS_LABELS.get(status, status.replace("_", " "))
    reason = _optional_text(provider.get("collection_reason"))
    if reason:
        return f"{label}: {reason.replace('_', ' ')}"
    return label


def window_status_label(window: Mapping[str, Any]) -> str:
    state = str(window.get("vendor_state") or "unknown")
    return _WINDOW_STATE_LABELS.get(state, state.replace("_", " "))


def collector_health_label(
    health: Mapping[str, Any] | None,
    *,
    reason: Any = None,
) -> str | None:
    """Return a compact human label for a public ``collector_health`` block."""
    if health is None:
        return None
    state = str(health.get("state") or "unknown")
    label = state.replace("_", " ")
    parts = [label]
    reason_text = _optional_text(reason)
    if reason_text is not None:
        parts.append(reason_text.replace("_", " "))
    failures = _failure_count(health)
    if failures is not None and (state != "ok" or failures > 0):
        parts.append(f"{failures}x")
    return " · ".join(parts)


def collector_health_style(health: Mapping[str, Any] | None) -> str:
    """Return the Rich style associated with a collector-health block."""
    if health is None:
        return ""
    state = str(health.get("state") or "")
    return _COLLECTOR_HEALTH_STYLES.get(state, "")


def _window_status_label_for_provider(
    provider: Mapping[str, Any],
    window: Mapping[str, Any],
) -> str:
    health_label = _unhealthy_collector_health_label(provider)
    if health_label is not None:
        return health_label
    return window_status_label(window)


def _window_source_label(window: Mapping[str, Any]) -> str:
    parts = [
        _optional_text(window.get("source")),
        _optional_text(window.get("freshness")),
        applicability_label(window.get("applicability")),
    ]
    return " · ".join(part for part in parts if part)


def _remaining_label(window: Mapping[str, Any]) -> str:
    used = _number(window.get("used_percent"))
    if used is None:
        return "-"
    return provider_usage_format_remaining_text(used)


def window_label(window: Mapping[str, Any]) -> str:
    label = _optional_text(window.get("label")) or _optional_text(window.get("key"))
    return label or "-"


def reset_label(
    window: Mapping[str, Any],
    now: float,
    *,
    verbose: bool,
) -> str:
    resets_at = _number(window.get("resets_at"))
    reset_passed = window.get("reset_passed") is True
    if resets_at is None:
        return "unknown"
    if reset_passed or resets_at <= now:
        return "reset passed"
    relative = f"in {duration_label(resets_at - now)}"
    if verbose:
        return f"{relative} ({timestamp_label(resets_at, now)})"
    return relative


def age_label(window: Mapping[str, Any]) -> str:
    age = _number(window.get("age_seconds"))
    if age is None:
        return "unknown"
    return duration_label(age)


def _age_from_timestamp(value: Any, now: float) -> str:
    timestamp = _number(value)
    if timestamp is None:
        return "unknown"
    return duration_label(max(now - timestamp, 0.0))


def timestamp_label(value: Any, now: float) -> str:
    timestamp = _number(value)
    if timestamp is None:
        return "unknown"
    if not math.isfinite(timestamp):
        return "unknown"
    absolute = format_local(timestamp, "%Y-%m-%d %H:%M:%S %Z", default="unknown")
    if absolute == "unknown":
        return "unknown"
    if timestamp > now:
        return absolute
    return f"{absolute} ({duration_label(now - timestamp)} ago)"


def duration_label(seconds: float) -> str:
    if not math.isfinite(seconds):
        return "unknown"
    whole = max(int(round(seconds)), 0)
    if whole < 60:
        return f"{whole}s"
    minutes = whole // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        remainder = minutes % 60
        return f"{hours}h" if remainder == 0 else f"{hours}h {remainder}m"
    days = hours // 24
    return f"{days}d"


def applicability_label(value: Any) -> str:
    if not isinstance(value, Mapping):
        return "unknown"
    kind = _optional_text(value.get("kind")) or "unknown"
    if kind == "account":
        return "account"
    if kind == "models":
        models = _string_list(value.get("model_ids"))
        return "models:" + ",".join(models) if models else "models"
    if kind == "model_family":
        family = _optional_text(value.get("family"))
        return f"family:{family}" if family else "model_family"
    if kind == "product":
        product = _optional_text(value.get("product"))
        models = _string_list(value.get("model_ids"))
        suffix = f":{','.join(models)}" if models else ""
        return f"product:{product or 'unknown'}{suffix}"
    return kind


def provider_style(provider: Mapping[str, Any]) -> str:
    health_style = collector_health_style(_provider_collector_health(provider))
    if health_style:
        return health_style
    status = str(provider.get("collection_status") or "")
    if status in {"error", "unauthenticated"}:
        return "yellow"
    return ""


def _provider_window_style(
    provider: Mapping[str, Any],
    window: Mapping[str, Any],
) -> str:
    health_style = collector_health_style(_provider_collector_health(provider))
    if health_style:
        return health_style
    return _window_style(window)


def _window_style(window: Mapping[str, Any]) -> str:
    attention = str(window.get("attention") or "")
    if attention in _ATTENTION_STYLES:
        return _ATTENTION_STYLES[attention]
    state = str(window.get("vendor_state") or "")
    if state == "rejected":
        return "bold red"
    if state == "warning":
        return "yellow"
    return ""


def diagnostic_line(diagnostic: Mapping[str, Any]) -> str:
    provider = diagnostic.get("provider") or "store"
    message = diagnostic.get("message") or ""
    return f"{provider}: {message}"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _provider_collector_health(provider: Mapping[str, Any]) -> Mapping[str, Any] | None:
    health = provider.get("collector_health")
    return health if isinstance(health, Mapping) else None


def _unhealthy_collector_health_label(provider: Mapping[str, Any]) -> str | None:
    health = _provider_collector_health(provider)
    if health is None:
        return None
    state = str(health.get("state") or "")
    if state not in {"degraded", "failing"}:
        return None
    return collector_health_label(health, reason=provider.get("collection_reason"))


def _failure_count(health: Mapping[str, Any]) -> int | None:
    value = health.get("consecutive_failures")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(float(value)):
        return None
    return max(int(value), 0)


def _string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value if str(item))


__all__ = [
    "age_label",
    "applicability_label",
    "collector_health_label",
    "collector_health_style",
    "diagnostic_line",
    "duration_label",
    "provider_status_label",
    "provider_style",
    "render_refresh_receipt_plain",
    "render_usage_plain",
    "render_usage_rich",
    "reset_label",
    "timestamp_label",
    "usage_snapshot_json_payload",
    "window_label",
    "window_status_label",
]
