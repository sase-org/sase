"""Compact ACE top-bar presentation for provider usage window indicators."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from rich.text import Text

from sase.ace.tui.provider_styles import provider_emoji_badge
from sase.llm_provider.usage.presentation import timestamp_label

from ._usage_indicator_format import (
    format_usage_compact_name,
    format_usage_countdown,
    format_usage_percent_text,
)
from ._usage_indicator_palette import (
    usage_badge_base_style,
    usage_disclosure_style,
    usage_divider_style,
    usage_gap_style,
    usage_neutral_color,
    usage_percent_color,
    usage_rejected_style,
    usage_value_style,
    usage_zero_percent_style,
)

_ATTENTION_RANK: Mapping[str, int] = {
    "rejected": 4,
    "very_low": 3,
    "collection_problem": 2,
    "low": 1,
    "none": 0,
}


@dataclass(frozen=True, slots=True)
class UsageWindowFragment:
    """One complete selected usage-window value within a provider group."""

    provider: str
    window_key: str
    attention_rank: int
    value_color: str
    text: Text
    tooltip_lines: tuple[str, ...]

    @property
    def width(self) -> int:
        """Return this badge's terminal-cell width."""
        return self.text.cell_len


@dataclass(frozen=True, slots=True)
class UsageProviderGroup:
    """One provider icon plus its selected usage windows in display order."""

    provider: str
    icon: str
    fragments: tuple[UsageWindowFragment, ...]

    @property
    def icon_width(self) -> int:
        """Return the provider icon's terminal-cell width."""
        return Text(self.icon).cell_len


def usage_indicator_groups(
    entries: Sequence[Mapping[str, Any]],
    *,
    dark: bool,
    now: float,
) -> tuple[UsageProviderGroup, ...]:
    """Build provider-grouped usage display data from selected projection entries."""
    by_provider: dict[str, list[Mapping[str, Any]]] = {}
    for entry in entries:
        provider = str(entry.get("provider") or "")
        by_provider.setdefault(provider, []).append(entry)

    records: list[tuple[tuple[Any, ...], UsageProviderGroup]] = []
    for provider, provider_entries in by_provider.items():
        ordered_entries = _ordered_provider_entries(provider_entries)
        named_entries = _entry_display_names(ordered_entries)
        fragments = tuple(
            _entry_fragment(entry, name=name, dark=dark, now=now)
            for entry, name in zip(ordered_entries, named_entries, strict=True)
        )
        if not fragments:
            continue
        group_rank = max(fragment.attention_rank for fragment in fragments)
        group = UsageProviderGroup(
            provider=provider,
            icon=_provider_icon(provider),
            fragments=fragments,
        )
        records.append(((-group_rank, provider), group))
    records.sort(key=lambda record: record[0])
    return tuple(group for _key, group in records)


def usage_indicator_open_provider(groups: Sequence[UsageProviderGroup]) -> str | None:
    """Return the provider a usage click should open, if any group is selected."""
    return groups[0].provider if groups else None


def usage_indicator_tooltip_lines(
    groups: Sequence[UsageProviderGroup],
) -> tuple[str, ...]:
    """Return full-disclosure tooltip lines for every selected and overflow badge."""
    lines: list[str] = []
    for group in groups:
        for fragment in group.fragments:
            lines.extend(fragment.tooltip_lines)
    return tuple(lines)


def build_usage_indicator_segment(
    groups: Sequence[UsageProviderGroup],
    *,
    budget: int | None = None,
    leading_space: bool = True,
    dark: bool = True,
) -> Text:
    """Return the richest complete-window prefix of *groups* that fits *budget*."""
    total = _window_count(groups)
    if not total:
        return Text("")
    full = _render_visible_windows(
        groups,
        visible_count=total,
        hidden_count=0,
        leading_space=leading_space,
        dark=dark,
    )
    if budget is None or full.cell_len <= budget:
        return full
    prefix_widths = _prefix_cell_widths(groups, leading_space=leading_space)
    for keep in range(total - 1, 0, -1):
        hidden = total - keep
        if prefix_widths[keep] + _overflow_width(hidden) <= budget:
            return _render_visible_windows(
                groups,
                visible_count=keep,
                hidden_count=hidden,
                leading_space=leading_space,
                dark=dark,
            )
    return _fallback_segment(
        total,
        budget=budget,
        leading_space=leading_space,
        dark=dark,
    )


def _fallback_segment(
    total: int,
    *,
    budget: int,
    leading_space: bool,
    dark: bool,
) -> Text:
    leading = " " if leading_space else ""
    for suffix in (f"usage {total}", str(total), "…"):
        text = Text(leading, style=usage_gap_style(dark=dark))
        text.append(suffix, style=usage_disclosure_style(dark=dark))
        if text.cell_len <= budget:
            return text
    return Text("")


def _render_visible_windows(
    groups: Sequence[UsageProviderGroup],
    *,
    visible_count: int,
    hidden_count: int,
    leading_space: bool,
    dark: bool,
) -> Text:
    visible_groups = _visible_groups(groups, visible_count)
    text = Text()
    if leading_space:
        text.append(" ", style=usage_gap_style(dark=dark))

    for group_index, (group, fragments) in enumerate(visible_groups):
        if group_index:
            previous_final = visible_groups[group_index - 1][1][-1]
            text.append(
                " |",
                style=usage_divider_style(previous_final.value_color, dark=dark),
            )
            text.append(" ", style=usage_gap_style(dark=dark))
        base_style = usage_badge_base_style(dark=dark)
        text.append(group.icon, style=base_style)
        text.append(" ", style=base_style)
        divider_style = usage_divider_style(fragments[-1].value_color, dark=dark)
        for fragment_index, fragment in enumerate(fragments):
            if fragment_index:
                text.append(" | ", style=divider_style)
            text.append_text(fragment.text)

    if hidden_count:
        text.append("  ", style=usage_gap_style(dark=dark))
        text.append(f"+{hidden_count}", style=usage_disclosure_style(dark=dark))
    return text


def _window_count(groups: Sequence[UsageProviderGroup]) -> int:
    return sum(len(group.fragments) for group in groups)


def _visible_groups(
    groups: Sequence[UsageProviderGroup],
    visible_count: int,
) -> tuple[tuple[UsageProviderGroup, tuple[UsageWindowFragment, ...]], ...]:
    remaining = visible_count
    visible: list[tuple[UsageProviderGroup, tuple[UsageWindowFragment, ...]]] = []
    for group in groups:
        if remaining <= 0:
            break
        count = min(len(group.fragments), remaining)
        if count:
            visible.append((group, group.fragments[:count]))
            remaining -= count
    return tuple(visible)


def _prefix_cell_widths(
    groups: Sequence[UsageProviderGroup],
    *,
    leading_space: bool,
) -> tuple[int, ...]:
    width = 1 if leading_space else 0
    widths = [width]
    previous_provider: str | None = None
    for group in groups:
        for fragment_index, fragment in enumerate(group.fragments):
            if previous_provider is None:
                width += group.icon_width + 1 + fragment.width
            elif fragment_index == 0:
                width += 2 + 1 + group.icon_width + 1 + fragment.width
            else:
                width += 3 + fragment.width
            widths.append(width)
            previous_provider = group.provider
    return tuple(widths)


def _overflow_width(hidden_count: int) -> int:
    return Text(f"  +{hidden_count}").cell_len


def _ordered_provider_entries(
    entries: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    defaults = [entry for entry in entries if entry.get("weekly_all") is True]
    anchor = min(defaults, key=_window_key_sort_text) if defaults else None
    extras = [entry for entry in entries if entry is not anchor]
    extras.sort(
        key=lambda entry: (-_entry_attention_rank(entry), _window_key_sort_text(entry))
    )
    if anchor is None:
        return tuple(extras)
    return (anchor, *extras)


def _entry_display_names(
    entries: Sequence[Mapping[str, Any]],
) -> tuple[str | None, ...]:
    names: list[str | None] = []
    for index, entry in enumerate(entries):
        if index == 0 and entry.get("weekly_all") is True:
            names.append(None)
        else:
            names.append(format_usage_compact_name(entry))

    counts: dict[str, int] = {}
    for name in names:
        if name is not None:
            counts[name] = counts.get(name, 0) + 1
    disambiguated: list[str | None] = []
    for entry, name in zip(entries, names, strict=True):
        if name is None or counts.get(name, 0) <= 1:
            disambiguated.append(name)
            continue
        key = _optional_text(entry.get("window_key")) or "?"
        disambiguated.append(f"{name} [{key.replace('|', '/')}]")
    return tuple(disambiguated)


def _entry_fragment(
    entry: Mapping[str, Any],
    *,
    name: str | None,
    dark: bool,
    now: float,
) -> UsageWindowFragment:
    provider = str(entry.get("provider") or "")
    remaining = _optional_float(entry.get("remaining_percent")) or 0.0
    freshness = _optional_text(entry.get("freshness")) or "unknown"
    reset_state = _optional_text(entry.get("reset_state")) or "unknown"
    stale = freshness in {"stale", "unknown"}
    passed = reset_state == "passed"
    base_style = usage_badge_base_style(dark=dark)

    if passed:
        percent_text = "?%"
        value_color = usage_neutral_color(dark=dark)
    else:
        percent_text = format_usage_percent_text(remaining)
        if stale:
            value_color = usage_neutral_color(dark=dark)
        else:
            value_color = usage_percent_color(remaining, dark=dark)

    countdown_text = format_usage_countdown(
        resets_at=_optional_float(entry.get("resets_at")),
        reset_state=reset_state,
        seconds_until_reset=_optional_float(entry.get("seconds_until_reset")),
    )
    value_style = usage_value_style(value_color, dark=dark)

    text = Text("", style=base_style)
    rejected = _optional_text(entry.get("vendor_state")) == "rejected"
    if name:
        text.append(name, style=value_style)
        text.append(" ", style=value_style if not rejected else base_style)
    if rejected:
        text.append("!", style=usage_rejected_style(dark=dark))
        text.append(" ", style=base_style)
    percent_style = (
        usage_zero_percent_style(dark=dark) if percent_text == "0%" else value_style
    )
    text.append(percent_text, style=percent_style)
    text.append(" ", style=value_style)
    text.append(countdown_text, style=value_style)

    tooltip = _entry_tooltip_lines(
        entry,
        provider=provider,
        now=now,
        stale=stale,
        passed=passed,
        freshness=freshness,
    )
    return UsageWindowFragment(
        provider=provider,
        window_key=_optional_text(entry.get("window_key")) or "",
        attention_rank=_entry_attention_rank(entry),
        value_color=value_color,
        text=text,
        tooltip_lines=tooltip,
    )


def _entry_attention_rank(entry: Mapping[str, Any]) -> int:
    return _ATTENTION_RANK.get(_optional_text(entry.get("display_attention")) or "", 0)


def _window_key_sort_text(entry: Mapping[str, Any]) -> str:
    return str(entry.get("window_key") or "")


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
        lines.append("last observed capacity; it may be out of date")
    if entry.get("collector_problem") is True:
        lines.append("collector is currently failing for this provider")
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
    "UsageProviderGroup",
    "UsageWindowFragment",
    "build_usage_indicator_segment",
    "usage_indicator_groups",
    "usage_indicator_open_provider",
    "usage_indicator_tooltip_lines",
]
