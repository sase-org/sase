"""Compact ACE top-bar presentation for provider usage window indicators."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from rich.text import Text

from sase.ace.tui.provider_styles import provider_emoji_badge
from sase.llm_provider.usage.presentation import (
    collector_health_label,
    duration_label,
    timestamp_label,
)

from ._usage_indicator_format import (
    format_usage_countdown,
    format_usage_percent_text,
    format_usage_specifier,
)
from ._usage_indicator_palette import (
    usage_neutral_color,
    usage_percent_color,
    usage_rejected_style,
    usage_secondary_style,
    usage_warning_style,
)

_ATTENTION_RANK: Mapping[str, int] = {
    "rejected": 4,
    "very_low": 3,
    "collection_problem": 2,
    "low": 1,
    "none": 0,
}


@dataclass(frozen=True, slots=True)
class UsageBadge:
    """One immutable, fully rendered usage-window badge for the top bar."""

    provider: str
    text: Text
    tooltip_lines: tuple[str, ...]

    @property
    def width(self) -> int:
        """Return this badge's terminal-cell width."""
        return self.text.cell_len


def usage_indicator_badges(
    entries: Sequence[Mapping[str, Any]],
    providers: Sequence[Mapping[str, Any]] = (),
    *,
    dark: bool,
    now: float,
) -> tuple[UsageBadge, ...]:
    """Build one badge per selected window, plus any standalone collector failure."""
    records: list[tuple[tuple[Any, ...], UsageBadge]] = [
        _entry_badge(entry, dark=dark, now=now) for entry in entries
    ]
    covered = {
        str(entry.get("provider"))
        for entry in entries
        if entry.get("collector_problem") is True
    }
    for provider in providers:
        name = _optional_text(provider.get("provider"))
        if not name or name in covered:
            continue
        if provider.get("collector_problem") is True:
            records.append(_collector_only_badge(name, provider, dark=dark, now=now))
    records.sort(key=lambda record: record[0])
    return tuple(badge for _key, badge in records)


def usage_indicator_open_provider(badges: Sequence[UsageBadge]) -> str | None:
    """Return the provider a usage click should open, if any badge is selected."""
    return badges[0].provider if badges else None


def usage_indicator_tooltip_lines(badges: Sequence[UsageBadge]) -> tuple[str, ...]:
    """Return full-disclosure tooltip lines for every selected and overflow badge."""
    lines: list[str] = []
    for badge in badges:
        lines.extend(badge.tooltip_lines)
    return tuple(lines)


def build_usage_indicator_segment(
    badges: Sequence[UsageBadge],
    *,
    budget: int | None = None,
    leading_space: bool = True,
    dark: bool = True,
) -> Text:
    """Return the richest whole-badge packing of *badges* that fits *budget*."""
    if not badges:
        return Text("")
    secondary = usage_secondary_style(dark=dark)
    leading = " " if leading_space else ""
    full = _join_badges(badges, leading=leading)
    if budget is None or full.cell_len <= budget:
        return full
    total = len(badges)
    for keep in range(total - 1, 0, -1):
        candidate = _join_badges(badges[:keep], leading=leading)
        candidate.append("  ", style=secondary)
        candidate.append(f"+{total - keep}", style=secondary)
        if candidate.cell_len <= budget:
            return candidate
    for text in (
        Text(f"{leading}usage {total}", style=secondary),
        Text(f"{leading}{total}", style=secondary),
        Text(f"{leading}…", style=secondary),
    ):
        if text.cell_len <= budget:
            return text
    return Text("")


def _join_badges(badges: Sequence[UsageBadge], *, leading: str) -> Text:
    text = Text(leading)
    for index, badge in enumerate(badges):
        if index:
            text.append("  ")
        text.append_text(badge.text)
    return text


def _entry_badge(
    entry: Mapping[str, Any],
    *,
    dark: bool,
    now: float,
) -> tuple[tuple[Any, ...], UsageBadge]:
    provider = str(entry.get("provider") or "")
    remaining = _optional_float(entry.get("remaining_percent")) or 0.0
    freshness = _optional_text(entry.get("freshness")) or "unknown"
    reset_state = _optional_text(entry.get("reset_state")) or "unknown"
    stale = freshness in {"stale", "unknown"}
    passed = reset_state == "passed"
    secondary_style = usage_secondary_style(dark=dark)

    if passed:
        percent_text = "?%"
        percent_style = usage_neutral_color(dark=dark)
    else:
        percent_text = format_usage_percent_text(remaining)
        if stale:
            percent_text = f"{percent_text}~"
            percent_style = usage_neutral_color(dark=dark)
        else:
            percent_style = usage_percent_color(remaining, dark=dark)

    countdown_text = format_usage_countdown(
        resets_at=_optional_float(entry.get("resets_at")),
        reset_state=reset_state,
        seconds_until_reset=_optional_float(entry.get("seconds_until_reset")),
    )
    specifier = format_usage_specifier(entry)

    marker: str | None = None
    marker_style: str | None = None
    if entry.get("collector_problem") is True:
        marker, marker_style = "⚠", usage_warning_style(dark=dark)
    elif _optional_text(entry.get("vendor_state")) == "rejected":
        marker, marker_style = "!", usage_rejected_style(dark=dark)

    text = Text(_provider_icon(provider))
    if marker:
        text.append(" ")
        text.append(marker, style=marker_style)
    if specifier:
        text.append(" ")
        text.append(specifier, style=secondary_style)
    text.append(" ")
    text.append(percent_text, style=f"bold {percent_style}")
    text.append(" ")
    text.append(countdown_text, style=secondary_style)

    tooltip = _entry_tooltip_lines(
        entry,
        provider=provider,
        now=now,
        stale=stale,
        passed=passed,
        freshness=freshness,
    )
    sort_key = _entry_sort_key(entry)
    return sort_key, UsageBadge(provider=provider, text=text, tooltip_lines=tooltip)


def _entry_sort_key(entry: Mapping[str, Any]) -> tuple[Any, ...]:
    rank = _ATTENTION_RANK.get(_optional_text(entry.get("display_attention")) or "", 0)
    return (
        -rank,
        str(entry.get("provider") or ""),
        not bool(entry.get("weekly_all")),
        str(entry.get("window_key") or ""),
    )


def _entry_tooltip_lines(
    entry: Mapping[str, Any],
    *,
    provider: str,
    now: float,
    stale: bool,
    passed: bool,
    freshness: str,
) -> tuple[str, ...]:
    label = _optional_text(entry.get("window_label")) or str(
        entry.get("window_key") or ""
    )
    key = _optional_text(entry.get("window_key")) or "?"
    remaining = _optional_float(entry.get("remaining_percent"))
    remaining_text = f"{remaining:g}% remaining" if remaining is not None else "unknown"
    lines = [f"{provider.upper()} - {label} (key {key}) · {remaining_text}"]
    scope_text = _scope_tooltip_text(entry.get("scope"))
    if scope_text:
        lines.append(f"scope: {scope_text}")
    policy_text = _policy_tooltip_text(entry.get("effective_policy"))
    if policy_text:
        source = _optional_text(entry.get("policy_source")) or "default"
        lines.append(f"policy: {policy_text} ({source})")
    resets_at = _optional_float(entry.get("resets_at"))
    if resets_at is None:
        lines.append("reset time unknown")
    elif passed:
        lines.append("reset passed; awaiting a new observation")
    else:
        lines.append(f"resets {timestamp_label(resets_at, now)}")
    lines.append(f"freshness: {freshness}")
    if stale and not passed:
        lines.append("~ shows the last observed capacity; it may be out of date")
    if entry.get("collector_problem") is True:
        lines.append("⚠ collector is currently failing for this provider")
    return tuple(lines)


def _scope_tooltip_text(scope: object) -> str | None:
    if not isinstance(scope, Mapping):
        return None
    kind = scope.get("kind")
    if kind == "all_models":
        return "all models"
    if kind == "unknown":
        label = _optional_text(scope.get("vendor_label")) or _optional_text(
            scope.get("vendor_id")
        )
        return f"unknown ({label})" if label else "unknown"
    if kind in {"models", "product"}:
        ids = scope.get("model_ids")
        joined = ",".join(ids) if isinstance(ids, list) and ids else "?"
        return f"models: {joined}"
    if kind == "model_family":
        family = _optional_text(scope.get("family")) or "?"
        return f"family: {family}"
    return None


def _policy_tooltip_text(policy: object) -> str | None:
    if not isinstance(policy, Mapping):
        return None
    kind = policy.get("kind")
    if kind == "below_remaining_percent":
        threshold = _optional_float(policy.get("below_remaining_percent"))
        return f"below {threshold:g}%" if threshold is not None else "below threshold"
    if isinstance(kind, str):
        return kind
    return None


def _collector_only_badge(
    provider: str,
    provider_status: Mapping[str, Any],
    *,
    dark: bool,
    now: float,
) -> tuple[tuple[Any, ...], UsageBadge]:
    text = Text(_provider_icon(provider))
    text.append(" ")
    text.append("⚠", style=usage_warning_style(dark=dark))
    lines = [f"{provider.upper()} - usage collection is failing"]
    health = provider_status.get("collector_health")
    if isinstance(health, Mapping):
        label = collector_health_label(
            health, reason=_optional_text(provider_status.get("diagnostic"))
        )
        if label:
            lines.append(f"collector health: {label}")
        since = _relative_age(health.get("failing_since"), now=now)
        if since is not None:
            lines.append(f"failing since: {since} ago")
        last_success = _relative_age(health.get("last_success_at"), now=now)
        lines.append(
            f"last success: {last_success} ago"
            if last_success is not None
            else "last success: unknown"
        )
    sort_key = (-_ATTENTION_RANK["collection_problem"], provider, True, "")
    return sort_key, UsageBadge(
        provider=provider, text=text, tooltip_lines=tuple(lines)
    )


def _relative_age(value: object, *, now: float) -> str | None:
    timestamp = _optional_float(value)
    if timestamp is None:
        return None
    return duration_label(max(now - timestamp, 0.0))


def _provider_icon(provider: str) -> str:
    icon = provider_emoji_badge(provider)
    if icon:
        return icon
    fallback = provider.strip().upper()[:4]
    return fallback or "?"


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


__all__ = [
    "UsageBadge",
    "build_usage_indicator_segment",
    "usage_indicator_badges",
    "usage_indicator_open_provider",
    "usage_indicator_tooltip_lines",
]
