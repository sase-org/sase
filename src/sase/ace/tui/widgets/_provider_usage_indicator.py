"""Compact ACE top-bar presentation for provider usage attention."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from rich.text import Text

from sase.llm_provider.usage.hints import CapacityHint
from sase.llm_provider.usage.presentation import collector_health_label, duration_label
from sase.llm_provider.usage.store import provider_usage_format_remaining_text

from ._override_pill import PROVIDER_USAGE_FAILING_PALETTE, PROVIDER_USAGE_PALETTE

_TOKEN_RE = re.compile(r"[A-Za-z0-9_.:@+=%-]+")
_INCLUDED_ALLOWANCE_WORDS = frozenset({"included", "allowance"})
_GENERIC_WINDOW_WORDS = frozenset(
    {
        "all",
        "five",
        "hour",
        "hours",
        "limit",
        "model",
        "models",
        "month",
        "monthly",
        "session",
        "seven",
        "week",
        "weekly",
        "window",
    }
)


@dataclass(frozen=True, slots=True)
class _UsageIndicatorPresentation:
    """Immutable display record for one attention hint and its source window."""

    kind: str
    marker: str
    provider: str
    original_label: str
    window_key: str | None
    window_label: str | None
    remaining: str | None
    window_scope: str | None
    freshness: str | None
    reset_passed: bool
    collection_reason: str | None
    collector_health: Mapping[str, Any] | None

    @property
    def normal_label(self) -> str:
        """Return the richest complete label available for the top bar."""
        if self.remaining and self.window_scope:
            return f"{self.remaining} · {self.window_scope}"
        return self.original_label

    @property
    def tooltip_line(self) -> str:
        """Return the full-disclosure usage tooltip line for this item."""
        details: list[str] = [self.original_label]
        if self.window_label and self.window_label not in self.original_label:
            details.append(f"window {self.window_label}")
        if self.freshness:
            details.append(self.freshness)
        if self.reset_passed:
            details.append("reset passed")
        return (
            f"{self.provider.upper()} - {self.kind.replace('_', ' ')} · "
            + " · ".join(details)
        )

    def tooltip_lines(self, *, now: float | None = None) -> tuple[str, ...]:
        """Return full-disclosure tooltip lines for this usage item."""
        return (
            self.tooltip_line,
            *_collector_health_tooltip_lines(
                self.collector_health,
                reason=self.collection_reason,
                now=now,
            ),
        )


@dataclass(frozen=True, slots=True)
class _UsageIndicatorCandidate:
    """One complete display candidate in the top-bar disclosure ladder."""

    name: str
    text: Text

    @property
    def width(self) -> int:
        """Return this candidate's terminal-cell width."""
        return self.text.cell_len


def usage_indicator_presentations(
    hints: Sequence[CapacityHint],
    providers: Sequence[Mapping[str, Any]] = (),
) -> tuple[_UsageIndicatorPresentation, ...]:
    """Resolve hint windows and produce immutable usage-indicator records."""
    indexed = _providers_by_name(providers)
    return tuple(
        _presentation_from_hint(hint, indexed.get(hint.provider)) for hint in hints
    )


def build_usage_indicator_segment(
    presentations: Sequence[_UsageIndicatorPresentation],
    *,
    budget: int | None = None,
    leading_space: bool = True,
) -> Text:
    """Return the richest usage segment that fits *budget* terminal cells."""
    if not presentations:
        return Text("")
    candidates = _progressively_shorter_candidates(
        _usage_indicator_candidates(
            presentations,
            leading_space=leading_space,
        )
    )
    if budget is None:
        return candidates[0].text
    for candidate in candidates:
        if candidate.width <= budget:
            return candidate.text
    return candidates[-1].text


def usage_indicator_tooltip_lines(
    presentations: Sequence[_UsageIndicatorPresentation],
    *,
    now: float | None = None,
) -> tuple[str, ...]:
    """Return full usage-disclosure lines for the indicator tooltip."""
    lines: list[str] = []
    for item in presentations:
        lines.extend(item.tooltip_lines(now=now))
    return tuple(lines)


def _usage_indicator_candidates(
    presentations: Sequence[_UsageIndicatorPresentation],
    *,
    leading_space: bool,
) -> tuple[_UsageIndicatorCandidate, ...]:
    leading = " " if leading_space else ""
    marker = presentations[0].marker
    palette = _usage_palette(presentations[0])
    provider = presentations[0].provider.upper()
    total = len(presentations)
    additional = total - 1
    return (
        _UsageIndicatorCandidate(
            "normal",
            _normal_candidate(
                marker,
                provider,
                presentations[0],
                additional=additional,
                leading=leading,
                palette=palette,
            ),
        ),
        _UsageIndicatorCandidate(
            "provider",
            _provider_disclosure_candidate(
                marker,
                provider,
                additional=additional,
                leading=leading,
                palette=palette,
            ),
        ),
        _UsageIndicatorCandidate(
            "total",
            _total_count_candidate(
                marker, total=total, leading=leading, palette=palette
            ),
        ),
        _UsageIndicatorCandidate(
            "micro",
            _micro_count_candidate(
                marker, total=total, leading=leading, palette=palette
            ),
        ),
    )


def _progressively_shorter_candidates(
    candidates: Sequence[_UsageIndicatorCandidate],
) -> tuple[_UsageIndicatorCandidate, ...]:
    selected: list[_UsageIndicatorCandidate] = []
    previous_width: int | None = None
    for candidate in candidates:
        if previous_width is None or candidate.width < previous_width:
            selected.append(candidate)
            previous_width = candidate.width
    return tuple(selected)


def _normal_candidate(
    marker: str,
    provider: str,
    presentation: _UsageIndicatorPresentation,
    *,
    additional: int,
    leading: str,
    palette: Any,
) -> Text:
    text = Text(leading, style=palette.base_style)
    text.append(marker, style=palette.base_style)
    text.append(" ", style=palette.secondary_style)
    text.append(provider, style=palette.base_style)
    text.append(" ", style=palette.secondary_style)
    if (
        presentation.kind != "collection_problem"
        and presentation.remaining
        and presentation.window_scope
    ):
        _append_remaining(text, presentation.remaining, palette=palette)
        text.append(" · ", style=palette.secondary_style)
        text.append(presentation.window_scope, style=palette.secondary_style)
    else:
        text.append(presentation.original_label, style=palette.secondary_style)
    if additional:
        text.append(f" +{additional}", style=palette.secondary_style)
    text.append(" ", style=palette.secondary_style)
    return text


def _provider_disclosure_candidate(
    marker: str,
    provider: str,
    *,
    additional: int,
    leading: str,
    palette: Any,
) -> Text:
    text = Text(leading, style=palette.base_style)
    text.append(marker, style=palette.base_style)
    text.append(" ", style=palette.secondary_style)
    text.append(provider, style=palette.base_style)
    if additional:
        text.append(f" +{additional}", style=palette.secondary_style)
    text.append(" ", style=palette.secondary_style)
    return text


def _total_count_candidate(
    marker: str,
    *,
    total: int,
    leading: str,
    palette: Any,
) -> Text:
    text = Text(leading, style=palette.base_style)
    text.append(marker, style=palette.base_style)
    text.append(" usage ", style=palette.secondary_style)
    text.append(str(total), style=palette.secondary_style)
    text.append(" ", style=palette.secondary_style)
    return text


def _micro_count_candidate(
    marker: str,
    *,
    total: int,
    leading: str,
    palette: Any,
) -> Text:
    text = Text(leading, style=palette.base_style)
    text.append(marker, style=palette.base_style)
    text.append(str(total), style=palette.secondary_style)
    text.append(" ", style=palette.secondary_style)
    return text


def _append_remaining(text: Text, remaining: str, *, palette: Any) -> None:
    if remaining.endswith(" left"):
        value = remaining[: -len(" left")]
        text.append(value, style=palette.base_style)
        text.append(" left", style=palette.secondary_style)
        return
    text.append(remaining, style=palette.base_style)


def _presentation_from_hint(
    hint: CapacityHint,
    provider: Mapping[str, Any] | None,
) -> _UsageIndicatorPresentation:
    window = _window_by_key(_windows(provider), hint.window_key) if provider else None
    window_label = _optional_text(window.get("label")) if window else None
    return _UsageIndicatorPresentation(
        kind=hint.kind,
        marker=hint.marker,
        provider=hint.provider,
        original_label=hint.label,
        window_key=hint.window_key,
        window_label=window_label,
        remaining=_remaining_text(window, hint),
        window_scope=_window_scope_token(hint, window),
        freshness=_optional_text(window.get("freshness")) if window else None,
        reset_passed=bool(window and window.get("reset_passed") is True),
        collection_reason=(
            _optional_text(provider.get("collection_reason")) if provider else None
        ),
        collector_health=_collector_health(provider),
    )


def _usage_palette(presentation: _UsageIndicatorPresentation) -> Any:
    if presentation.kind == "collection_problem":
        return PROVIDER_USAGE_FAILING_PALETTE
    return PROVIDER_USAGE_PALETTE


def _collector_health_tooltip_lines(
    health: Mapping[str, Any] | None,
    *,
    reason: str | None,
    now: float | None,
) -> tuple[str, ...]:
    if health is None:
        return ()
    state = health.get("state")
    if state not in {"degraded", "failing"}:
        return ()
    lines: list[str] = []
    label = collector_health_label(health, reason=reason)
    if label is not None:
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
    return tuple(lines)


def _collector_health(
    provider: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if provider is None:
        return None
    health = provider.get("collector_health")
    return health if isinstance(health, Mapping) else None


def _relative_age(value: object, *, now: float | None) -> str | None:
    timestamp = _optional_float(value)
    if timestamp is None:
        return None
    clock = time.time() if now is None else float(now)
    return duration_label(max(clock - timestamp, 0.0))


def _window_scope_token(
    hint: CapacityHint,
    window: Mapping[str, Any] | None,
) -> str | None:
    if window is None:
        return None
    scope = _scope_token(hint, window.get("applicability"))
    period = _period_token(window)
    bucket = _bucket_token(
        provider=hint.provider,
        label=_optional_text(window.get("label")),
        period=period,
        scope=scope,
    )
    parts = [part for part in (bucket, period, scope) if part]
    return "/".join(parts) if parts else None


def _scope_token(hint: CapacityHint, applicability: object) -> str:
    if hint.scope == "scope unknown":
        return "scope?"
    if not isinstance(applicability, Mapping):
        return "scope?"
    kind = _optional_text(applicability.get("kind")) or "unknown"
    if kind == "account":
        return "all"
    if kind == "models":
        return _joined_strings(applicability.get("model_ids")) or "scope?"
    if kind == "product":
        models = _joined_strings(applicability.get("model_ids"))
        product = _optional_text(applicability.get("product"))
        if product and models:
            return f"{product}:{models}"
        return models or "scope?"
    if kind == "model_family":
        family = _optional_text(applicability.get("family"))
        models = _joined_strings(applicability.get("model_ids"))
        if family:
            return f"family:{family}"
        return models or "scope?"
    return "scope?"


def _period_token(window: Mapping[str, Any]) -> str | None:
    label = _optional_text(window.get("label"))
    alias = _period_alias_from_label(label)
    if alias in {"wk", "mo"}:
        return alias
    duration = _optional_float(window.get("duration_seconds"))
    duration_token = _duration_token(duration)
    if duration_token:
        return duration_token
    return alias


def _duration_token(seconds: float | None) -> str | None:
    if seconds is None or not math.isfinite(seconds) or seconds <= 0:
        return None
    rounded = int(round(seconds))
    if not math.isclose(seconds, float(rounded), abs_tol=0.001):
        return None
    if rounded % 86_400 == 0:
        days = rounded // 86_400
        return "wk" if days == 7 else f"{days}d"
    if rounded % 3_600 == 0:
        return f"{rounded // 3_600}h"
    if rounded % 60 == 0:
        return f"{rounded // 60}m"
    return None


def _period_alias_from_label(label: str | None) -> str | None:
    if not label:
        return None
    normalized = " ".join(token.casefold() for token in _TOKEN_RE.findall(label))
    if "month" in normalized or "monthly" in normalized:
        return "mo"
    if (
        "week" in normalized
        or "weekly" in normalized
        or "seven day" in normalized
        or "7 day" in normalized
    ):
        return "wk"
    if (
        "5h" in normalized
        or "5 hour" in normalized
        or "5-hour" in normalized
        or "five hour" in normalized
        or "five-hour" in normalized
    ):
        return "5h"
    if "session" in normalized:
        return "session"
    return None


def _bucket_token(
    *,
    provider: str,
    label: str | None,
    period: str | None,
    scope: str,
) -> str | None:
    if not label:
        return None
    tokens = _TOKEN_RE.findall(label)
    if tokens and tokens[0].casefold() == provider.casefold():
        tokens = tokens[1:]
    if not tokens:
        return None
    period_words = _period_words(period)
    scope_words = frozenset(part.casefold() for part in _TOKEN_RE.findall(scope))
    remaining = [
        token
        for token in tokens
        if token.casefold()
        not in _GENERIC_WINDOW_WORDS
        | _INCLUDED_ALLOWANCE_WORDS
        | period_words
        | scope_words
    ]
    if not remaining:
        return None
    if _looks_like_included_allowance(tokens) and len(remaining) == len(tokens):
        return None
    return " ".join(remaining)


def _period_words(period: str | None) -> frozenset[str]:
    if period == "wk":
        return frozenset({"7", "7d", "week", "weekly", "seven", "day"})
    if period == "mo":
        return frozenset({"month", "monthly"})
    if period == "5h":
        return frozenset({"5", "5h", "5-hour", "five", "five-hour", "hour", "hours"})
    if period == "session":
        return frozenset({"session"})
    return frozenset()


def _looks_like_included_allowance(tokens: Sequence[str]) -> bool:
    words = {token.casefold() for token in tokens}
    return _INCLUDED_ALLOWANCE_WORDS <= words


def _remaining_text(
    window: Mapping[str, Any] | None,
    hint: CapacityHint,
) -> str | None:
    if window is not None:
        used = _optional_float(window.get("used_percent"))
        if used is not None:
            try:
                return provider_usage_format_remaining_text(used)
            except Exception:
                return _format_remaining_percent(max(0.0, 100.0 - used))
        remaining = _optional_float(window.get("remaining_percent"))
        if remaining is not None:
            return _format_remaining_percent(remaining)
    label_remaining = hint.label.split(" · ", 1)[0].strip()
    if label_remaining.endswith("% left") or label_remaining.startswith("<1% left"):
        return label_remaining
    if hint.remaining_percent is not None:
        return _format_remaining_percent(hint.remaining_percent)
    return None


def _format_remaining_percent(remaining: float) -> str:
    if 0.0 < remaining < 1.0:
        return "<1% left"
    return f"{_format_number(remaining)}% left"


def _window_by_key(
    windows: Sequence[Mapping[str, Any]],
    key: str | None,
) -> Mapping[str, Any] | None:
    if not key:
        return None
    for window in windows:
        if window.get("key") == key:
            return window
    return None


def _windows(provider: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
    if provider is None:
        return ()
    raw = provider.get("windows")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _providers_by_name(
    providers: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for provider in providers:
        name = _optional_text(provider.get("provider"))
        if name:
            indexed[name] = provider
    return indexed


def _joined_strings(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    strings = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return ",".join(strings) if strings else None


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _optional_float(value: object) -> float | None:
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
