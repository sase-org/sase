"""Pure text formatting for the compact top-bar usage indicator."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from sase.llm_provider.registry import model_short_alias_map

_SESSION_TOKEN = "5h"


def format_usage_percent_text(remaining_percent: float) -> str:
    """Floor a clamped remaining percentage; ``<1%``, ``0%``, and ``100%`` are exact."""
    if not math.isfinite(remaining_percent):
        remaining_percent = 0.0
    clamped = max(0.0, min(100.0, remaining_percent))
    if clamped <= 0.0:
        return "0%"
    if clamped < 1.0:
        return "<1%"
    if clamped >= 100.0:
        return "100%"
    return f"{math.floor(clamped)}%"


def format_usage_countdown(
    *,
    resets_at: float | None,
    reset_state: str | None,
    seconds_until_reset: float | None,
) -> str:
    """Render the two-unit reset countdown, or ``?``/``0h0m↻`` for unknown/passed."""
    if resets_at is None or reset_state == "unknown":
        return "?"
    if reset_state == "passed":
        return "0h0m↻"
    seconds = seconds_until_reset if seconds_until_reset is not None else 0.0
    return _two_unit_countdown(seconds)


def _two_unit_countdown(seconds: float) -> str:
    if not math.isfinite(seconds):
        seconds = 0.0
    seconds = max(seconds, 0.0)
    if seconds >= 86_400:
        days, remainder = divmod(int(seconds), 86_400)
        hours = remainder // 3_600
        return f"{days}d{hours}h"
    hours, remainder = divmod(int(seconds), 3_600)
    minutes = remainder // 60
    if hours == 0 and minutes == 0:
        minutes = 1
    return f"{hours}h{minutes}m"


def format_usage_compact_name(entry: Mapping[str, Any]) -> str:
    """Return the grouped-indicator name for a non-default usage window.

    Weekly periods and all-model scopes are omitted in the compact form. If that
    simplification removes every useful component, fall back to the full specifier,
    then to the exact window key, and finally to ``?``.
    """
    compact = _usage_specifier(entry, compact=True)
    if compact:
        return compact
    full = _usage_specifier(entry, compact=False)
    if full:
        return full
    key = _optional_text(entry.get("window_key"))
    return (_sanitize_usage_label(key) or "?") if key else "?"


def _usage_specifier(entry: Mapping[str, Any], *, compact: bool) -> str | None:
    scope = entry.get("scope")
    scope = scope if isinstance(scope, Mapping) else {}
    period = entry.get("period")
    period = period if isinstance(period, Mapping) else {}
    bucket = _scope_bucket_prefix(scope)
    period_token = _period_token(period)
    suffix = _scope_suffix(scope)
    if compact:
        if period_token == "wk":
            period_token = None
        if suffix == "all":
            suffix = None
    parts = [
        sanitized
        for part in (bucket, period_token, suffix)
        if (sanitized := _sanitize_usage_label(part))
    ]
    return "/".join(parts) if parts else None


def _period_token(period: Mapping[str, Any]) -> str | None:
    kind = period.get("kind")
    if kind == "session":
        return _SESSION_TOKEN
    if kind == "weekly":
        return "wk"
    if kind == "monthly":
        return "mo"
    if kind == "duration":
        return _duration_token(_optional_float(period.get("duration_seconds")))
    return None


def _duration_token(seconds: float | None) -> str | None:
    if seconds is None or not math.isfinite(seconds) or seconds <= 0:
        return None
    total_minutes = round(seconds / 60.0)
    if total_minutes <= 0:
        return None
    days, remainder = divmod(total_minutes, 1_440)
    hours, minutes = divmod(remainder, 60)
    if days and not hours and not minutes:
        return f"{days}d"
    if days:
        return f"{days}d{hours}h" if hours else f"{days}d"
    if hours and not minutes:
        return f"{hours}h"
    if hours:
        return f"{hours}h{minutes}m"
    if minutes:
        return f"{minutes}m"
    return None


def _scope_bucket_prefix(scope: Mapping[str, Any]) -> str | None:
    if scope.get("kind") != "unknown":
        return None
    label = _optional_text(scope.get("vendor_label")) or _optional_text(
        scope.get("vendor_id")
    )
    return label


def _scope_suffix(scope: Mapping[str, Any]) -> str | None:
    kind = scope.get("kind")
    if kind == "all_models":
        return "all"
    if kind == "unknown":
        return "scope?"
    if kind in {"models", "product"}:
        return _model_ids_token(scope.get("model_ids"))
    if kind == "model_family":
        family = _optional_text(scope.get("family"))
        if family:
            return f"family:{family}"
        return _model_ids_token(scope.get("model_ids"))
    return None


def _model_ids_token(model_ids: object) -> str | None:
    if not isinstance(model_ids, list):
        return None
    ids = [item.strip() for item in model_ids if isinstance(item, str) and item.strip()]
    if not ids:
        return None
    aliases = model_short_alias_map()
    shortened = [aliases.get(model_id, model_id) for model_id in ids]
    if len(set(shortened)) != len(set(ids)):
        shortened = ids
    return ",".join(dict.fromkeys(shortened))


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


_WHITESPACE_RE = re.compile(r"\s+")


def _sanitize_usage_label(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKC", value)
    cleaned = "".join(
        " "
        if character.isspace() or unicodedata.category(character)[0] == "C"
        else character
        for character in normalized
    )
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip().replace("|", "/")
    return cleaned or None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


__all__ = [
    "format_usage_compact_name",
    "format_usage_countdown",
    "format_usage_percent_text",
]
