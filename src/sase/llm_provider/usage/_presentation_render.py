"""Plain-text, Rich, and refresh-receipt renderers for usage presentation."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any

from sase.llm_provider.usage._presentation_labels import (
    age_label,
    applicability_label,
    collector_retry_label,
    diagnostic_line,
    duration_label,
    provider_status_label,
    provider_style,
    provider_window_style,
    reset_label,
    timestamp_label,
    window_label,
    window_status_label_for_provider,
)
from sase.llm_provider.usage._presentation_shared import (
    failure_count,
    finite_number,
    format_remaining_text,
    nonblank_text,
    provider_collector_health,
)
from sase.llm_provider.usage._presentation_snapshot import (
    display_provider_rows,
    usage_diagnostic_to_json,
)
from sase.llm_provider.usage.store import ProviderUsageStoreDiagnostic

_PLAIN_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:/@+=%-]+$")


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
    rows = list(display_provider_rows(snapshot, requested_providers))
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
        diagnostic = usage_diagnostic_to_json(item)
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
    rows = list(display_provider_rows(snapshot, requested_providers))
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
        table.add_column("Retry", no_wrap=True)

    for provider in rows:
        windows = _window_rows(provider)
        retry_label = (
            collector_retry_label(provider_collector_health(provider), clock)
            if verbose
            else None
        )
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
                values.append(nonblank_text(provider.get("diagnostic")) or "-")
                values.append(retry_label or "-")
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
                window_status_label_for_provider(provider, window),
            ]
            if verbose:
                values.append(_window_source_label(window))
                if index == 0 and retry_label is not None:
                    values.append(retry_label)
                else:
                    values.append("")
            table.add_row(*values, style=provider_window_style(provider, window))

    diagnostic_lines = tuple(
        diagnostic_line(usage_diagnostic_to_json(item)) for item in diagnostics
    )
    if diagnostic_lines:
        return Group(table, Text("\n".join(diagnostic_lines), style="yellow"))
    return table


def render_usage_refresh_toast(receipt: Any, *, now: float | None = None) -> str:
    """Render a refresh receipt as one compact toast line.

    Started providers lead (``"Refreshing usage: claude, codex"``) with any
    deferral appended (``" · grok rate limited · retry in 52m"``). When
    nothing started, the deferral reasons stand alone so a toast never claims
    work is running that is not.
    """
    clock = time.time() if now is None else now
    providers = tuple(getattr(receipt, "providers", ()) or ())
    started = [
        str(getattr(item, "provider", "") or "")
        for item in providers
        if getattr(item, "operation_id", None)
    ]
    started = [name for name in started if name]
    deferred = [
        _usage_refresh_deferral_detail(item, clock)
        for item in providers
        if not getattr(item, "operation_id", None)
        and str(getattr(item, "provider", "") or "")
    ]
    if started:
        toast = "Refreshing usage: " + ", ".join(started)
        if deferred:
            toast += " · " + " · ".join(deferred)
        return toast
    if deferred:
        return "Usage refresh deferred: " + " · ".join(deferred)
    return "Usage refresh: nothing due"


def _usage_refresh_deferral_detail(item: Any, now: float) -> str:
    """Render one non-started receipt provider as ``"<name> <reason>"``."""
    provider = str(getattr(item, "provider", "") or "")
    reason = getattr(item, "reason", None)
    reason_text = str(reason).strip() if isinstance(reason, str) else ""
    label = collector_retry_label(
        {
            "last_failure_reason": reason_text or None,
            "retry_at": getattr(item, "due_at", None),
        },
        now,
    )
    detail = label or str(getattr(item, "status", "") or "deferred")
    return f"{provider} {detail}" if provider else detail


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
        used = finite_number(summary.get("used_percent"))
        if used is not None:
            values["remaining"] = format_remaining_text(used)
            values["used_percent"] = _format_number(used)
        freshness = nonblank_text(summary.get("freshness"))
        if freshness is not None:
            values["freshness"] = freshness
    reason = nonblank_text(provider.get("collection_reason"))
    if reason is not None:
        values["reason"] = reason
    diagnostic = nonblank_text(provider.get("diagnostic"))
    if diagnostic is not None:
        values["diagnostic"] = diagnostic
    if verbose:
        health = provider_collector_health(provider)
        if health is not None:
            values["health"] = str(health.get("state") or "unknown")
            failures = failure_count(health)
            if failures is not None:
                values["consecutive_failures"] = failures
            values["last_success"] = timestamp_label(health.get("last_success_at"), now)
            values["failing_since"] = timestamp_label(health.get("failing_since"), now)
            retry_label = collector_retry_label(health, now)
            if retry_label is not None:
                values["retry"] = retry_label
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
    used = finite_number(window.get("used_percent"))
    values: dict[str, Any] = {
        "provider": provider,
        "key": window.get("key") or "",
        "label": window.get("label") or window.get("key") or "",
        "remaining": "-" if used is None else format_remaining_text(used),
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
        exceeded = finite_number(window.get("exceeded_by_percent"))
        if exceeded is not None:
            values["exceeded_by_percent"] = _format_number(exceeded)
    return _plain_record("window", **values)


def _window_rows(provider: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = provider.get("windows")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _age_from_timestamp(value: Any, now: float) -> str:
    timestamp = finite_number(value)
    if timestamp is None:
        return "unknown"
    return duration_label(max(now - timestamp, 0.0))


def _window_source_label(window: Mapping[str, Any]) -> str:
    parts = [
        nonblank_text(window.get("source")),
        nonblank_text(window.get("freshness")),
        applicability_label(window.get("applicability")),
    ]
    return " · ".join(part for part in parts if part)


def _remaining_label(window: Mapping[str, Any]) -> str:
    used = finite_number(window.get("used_percent"))
    if used is None:
        return "-"
    return format_remaining_text(used)


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
