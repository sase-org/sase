"""Pure Rich rendering helpers for the ACE Providers · Usage view.

Shares the same domain-derived label helpers as ``sase usage list`` (see
``sase.llm_provider.usage.presentation``) so ACE and the CLI never duplicate
freshness, reset, or scope computations.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rich.text import Text

from sase.llm_provider.usage.presentation import (
    age_label,
    applicability_label,
    collector_health_style,
    diagnostic_line,
    duration_label,
    provider_status_label,
    provider_style,
    reset_label,
    timestamp_label,
    window_label,
    window_status_label,
)
from sase.llm_provider.usage.store import provider_usage_format_remaining_text

METER_WIDTH = 10
DETAIL_COLUMNS_WIDE = (
    "Window",
    "Remaining",
    "Scope",
    "Reset",
    "Age",
    "State",
    "Source",
)
DETAIL_COLUMNS_NARROW = ("Window", "Remaining", "Scope / Reset / Age", "State")

_WIDE_MIN_COLUMNS = 120
_MEDIUM_MIN_COLUMNS = 80

_PROVIDER_ATTENTION_STYLES: Mapping[str, str] = {
    "rejected": "bold red",
    "very_low": "bold red",
    "low": "yellow",
    "collection_problem": "bold #FFAF5F",
}


def usage_view_width_tier(width: int) -> str:
    """Return the responsive breakpoint tier for a Usage view render width."""
    if width >= _WIDE_MIN_COLUMNS:
        return "wide"
    if width >= _MEDIUM_MIN_COLUMNS:
        return "medium"
    return "narrow"


def detail_columns_for_width(width: int) -> tuple[str, ...]:
    """Return the detail-table column headers for a render width."""
    if usage_view_width_tier(width) == "narrow":
        return DETAIL_COLUMNS_NARROW
    return DETAIL_COLUMNS_WIDE


def _usage_meter(remaining_percent: float | None, *, width: int = METER_WIDTH) -> str:
    """Return a colorless block gauge, or a placeholder for unknown remaining."""
    if remaining_percent is None:
        return "?" * width
    clamped = max(0.0, min(100.0, float(remaining_percent)))
    filled = max(0, min(width, round((clamped / 100.0) * width)))
    return "█" * filled + "░" * (width - filled)


def _provider_attention_style(provider: Mapping[str, Any]) -> str:
    """Return the Rich style for a provider row, from its attention kind."""
    attention = provider.get("attention")
    kind = attention.get("kind") if isinstance(attention, Mapping) else None
    if isinstance(kind, str) and kind in _PROVIDER_ATTENTION_STYLES:
        return _PROVIDER_ATTENTION_STYLES[kind]
    return provider_style(provider)


def provider_summary_text(
    provider: Mapping[str, Any],
    *,
    updating: bool = False,
    width: int = _WIDE_MIN_COLUMNS,
) -> Text:
    """Return the one-line provider row shown in the Usage list.

    Meters are decoration, not information (the remaining-percent text next
    to them says the same thing); they drop first as the view narrows below
    the wide breakpoint, per the responsive layout rules.
    """
    name = str(provider.get("provider") or "?").upper()
    style = _provider_attention_style(provider)
    text = Text(f"{name:<8} ", style="bold")
    summary = provider.get("summary")
    remaining = (
        summary.get("remaining_percent") if isinstance(summary, Mapping) else None
    )
    if isinstance(remaining, int | float):
        used = summary.get("used_percent") if isinstance(summary, Mapping) else None
        remaining_text = (
            provider_usage_format_remaining_text(float(used))
            if isinstance(used, int | float)
            else f"{float(remaining):g}% left"
        )
        if usage_view_width_tier(width) == "wide":
            remaining_text = f"{_usage_meter(float(remaining))} {remaining_text}"
        text.append(remaining_text, style=style)
        scope = summary.get("scope") if isinstance(summary, Mapping) else None
        if isinstance(scope, Mapping):
            text.append(f" · {applicability_label(scope)}", style="dim")
        freshness = summary.get("freshness") if isinstance(summary, Mapping) else None
        if isinstance(freshness, str) and freshness != "fresh":
            text.append(f" ({freshness})", style="dim")
    else:
        text.append(provider_status_label(provider), style=style or "dim")
    _append_collector_failure_badge(text, provider)
    if updating:
        text.append("  Updating…", style="italic dim")
    return text


def provider_detail_header(provider: Mapping[str, Any], *, now: float) -> Text:
    """Return the detail-pane header line for one provider."""
    parts: list[str] = []
    plan = provider.get("plan")
    if isinstance(plan, str) and plan:
        parts.append(f"Plan: {plan}")
    mode = provider.get("account_mode")
    if isinstance(mode, str) and mode:
        parts.append(f"Mode: {mode}")
    parts.append(f"Status: {provider_status_label(provider)}")
    last_full = provider.get("last_full_observation_at")
    parts.append(f"Last observed: {timestamp_label(last_full, now)}")
    text = Text(" · ".join(parts))
    collector_detail = _collector_health_detail(provider, now=now)
    if collector_detail is not None:
        text.append("\n")
        text.append(
            collector_detail,
            style=collector_health_style(_provider_collector_health(provider)),
        )
    diagnostic = provider.get("diagnostic")
    if isinstance(diagnostic, str) and diagnostic:
        text.append("\n")
        text.append(
            diagnostic_line(
                {"provider": provider.get("provider"), "message": diagnostic}
            ),
            style="yellow",
        )
    return text


def window_detail_row(
    window: Mapping[str, Any],
    *,
    now: float,
    width: int = _WIDE_MIN_COLUMNS,
) -> tuple[str, ...]:
    """Return one detail-table row for a single usage window.

    Row length always matches :func:`detail_columns_for_width` for the same
    *width*, so columns and cells stay in sync as the view resizes.
    """
    used = window.get("used_percent")
    remaining_text = (
        provider_usage_format_remaining_text(float(used))
        if isinstance(used, int | float)
        else "-"
    )
    exceeded = window.get("exceeded_by_percent")
    if isinstance(exceeded, int | float) and exceeded > 0:
        remaining_text = f"exceeded by {exceeded:g}pp"
    scope = applicability_label(window.get("applicability"))
    reset = reset_label(window, now, verbose=True)
    age = age_label(window)
    state = window_status_label(window)
    if usage_view_width_tier(width) == "narrow":
        return (
            window_label(window),
            remaining_text,
            f"{scope} · {reset} · {age}",
            state,
        )
    return (
        window_label(window),
        remaining_text,
        scope,
        reset,
        age,
        state,
        str(window.get("source") or "unknown"),
    )


def _append_collector_failure_badge(text: Text, provider: Mapping[str, Any]) -> None:
    health = _provider_collector_health(provider)
    if _collector_health_state(health) != "failing":
        return
    text.append(" ⚠ failing", style=collector_health_style(health) or "bold #FFAF5F")


def _collector_health_detail(
    provider: Mapping[str, Any],
    *,
    now: float,
) -> str | None:
    health = _provider_collector_health(provider)
    state = _collector_health_state(health)
    if state not in {"degraded", "failing"} or health is None:
        return None
    parts: list[str] = []
    failures = _collector_failure_count(health)
    if failures is not None:
        noun = "failure" if failures == 1 else "failures"
        parts.append(f"{failures} {noun}")
    since = _relative_age(health.get("failing_since"), now=now)
    if since is not None:
        parts.append(f"since {since}")
    last_success = _relative_age(health.get("last_success_at"), now=now)
    parts.append(
        f"last success {last_success} ago"
        if last_success is not None
        else "last success unknown"
    )
    suffix = f" — {' · '.join(parts)}" if parts else ""
    return f"Collector: {state.replace('_', ' ')}{suffix}"


def _provider_collector_health(
    provider: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    health = provider.get("collector_health")
    return health if isinstance(health, Mapping) else None


def _collector_health_state(health: Mapping[str, Any] | None) -> str:
    if health is None:
        return ""
    state = health.get("state")
    return state if isinstance(state, str) else ""


def _collector_failure_count(health: Mapping[str, Any]) -> int | None:
    failures = health.get("consecutive_failures")
    if isinstance(failures, bool) or not isinstance(failures, int | float):
        return None
    return max(int(failures), 0)


def _relative_age(value: Any, *, now: float) -> str | None:
    timestamp = (
        value
        if isinstance(value, int | float) and not isinstance(value, bool)
        else None
    )
    if timestamp is None:
        return None
    return duration_label(max(now - float(timestamp), 0.0))


__all__ = [
    "DETAIL_COLUMNS_NARROW",
    "DETAIL_COLUMNS_WIDE",
    "METER_WIDTH",
    "detail_columns_for_width",
    "provider_detail_header",
    "provider_summary_text",
    "usage_view_width_tier",
    "window_detail_row",
]
