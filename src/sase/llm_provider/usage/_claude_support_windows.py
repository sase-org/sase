"""Claude usage-window parsing and vendor-state classification."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

from sase.llm_provider.usage._claude_support_reset_time import (
    parse_claude_reset_timestamp,
)
from sase.llm_provider.usage._claude_support_text import (
    label_words,
    normalize_text,
    slugify,
)
from sase.llm_provider.usage.types import (
    UsageProbeContext,
    bounded_probe_diagnostic,
    validate_observation,
    validated_status_observation,
)

_USAGE_ROW_RE = re.compile(
    r"^Current\s+(?P<label>[^:]+):\s*"
    r"(?P<percent>\d+(?:\.\d+)?)%\s+used"
    r"(?:\s+.*?\bresets?\s+(?P<reset>.+))?$",
    re.IGNORECASE,
)
_MODEL_LABELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("claude-fable-5", ("claude fable 5", "fable 5", "fable")),
    ("claude-haiku-4-5", ("claude haiku 4 5", "haiku 4 5", "haiku")),
    ("sonnet", ("sonnet",)),
    ("opus", ("opus",)),
)


def parse_usage_windows(
    result_text: str,
    *,
    observed_at: float,
) -> tuple[list[dict[str, Any]], str | None]:
    """Parse Claude usage prose into provider-usage windows."""
    windows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    had_non_reset_parse_error = False
    unparsed_reset_expressions: list[str] = []
    for raw_line in result_text.splitlines():
        line = normalize_text(raw_line)
        if not line:
            continue
        match = _USAGE_ROW_RE.match(line)
        if match is None:
            if line.startswith("Current ") or "% used" in line:
                had_non_reset_parse_error = True
            continue
        label = match.group("label").strip()
        percent_text = match.group("percent")
        reset_text = match.group("reset")
        try:
            used_percent = float(percent_text)
        except ValueError:
            had_non_reset_parse_error = True
            continue
        if used_percent < 0.0:
            had_non_reset_parse_error = True
            continue
        resets_at = None
        if reset_text:
            resets_at = parse_claude_reset_timestamp(
                reset_text,
                observed_at=observed_at,
            )
            if resets_at is None:
                unparsed_reset_expressions.append(reset_text)
        key, display_label, applicability = _usage_window_identity(label)
        if key in seen_keys:
            had_non_reset_parse_error = True
            continue
        seen_keys.add(key)
        windows.append(
            {
                "key": key,
                "label": display_label,
                "used_percent": used_percent,
                "resets_at": resets_at,
                "duration_seconds": None,
                "period_start": None,
                "applicability": applicability,
                "observed_at": observed_at,
                "source": "probe",
                "vendor_state": "allowed",
            }
        )
    return windows, _usage_parse_diagnostic(
        unparsed_reset_expressions,
        had_non_reset_parse_error=had_non_reset_parse_error,
    )


def event_window(
    raw_key: str,
    used_percent: float,
    resets_at: float | None,
    observed_at: float,
) -> dict[str, Any]:
    """Normalize a Claude stream window name into a provider-usage window."""
    normalized = slugify(raw_key)
    if normalized in {"five-hour", "five-hour-limit", "five-hour-window", "5-hour"}:
        key = "session"
        label = "Claude five-hour session"
        applicability = {"kind": "product", "product": "claude"}
    elif normalized in {
        "seven-day",
        "seven-day-limit",
        "seven-day-window",
        "7-day",
    }:
        key = "weekly"
        label = "Claude weekly all models"
        applicability = {"kind": "product", "product": "claude"}
    else:
        key = f"window:{normalized}"
        label = f"Claude {raw_key}"
        applicability = {
            "kind": "unknown",
            "vendor_label": raw_key,
            "vendor_id": normalized,
        }
    return {
        "key": key,
        "label": label,
        "used_percent": used_percent,
        "resets_at": resets_at,
        "duration_seconds": None,
        "period_start": None,
        "applicability": applicability,
        "observed_at": observed_at,
        "source": "stream_event",
        "vendor_state": "unknown",
    }


def has_zero_cost_markers(payload: Mapping[str, Any]) -> bool:
    """Return whether Claude result JSON proves zero turns and zero cost."""
    turns = payload.get("num_turns")
    cost = payload.get("total_cost_usd")
    return _numeric_zero(turns) and _numeric_zero(cost)


def optional_epoch_seconds(value: object) -> float | Literal["malformed"] | None:
    """Parse an optional stream reset timestamp already represented as epoch."""
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not is_finite_number(value)
    ):
        return "malformed"
    return float(value)


def vendor_state_from_rate_limit_info(info: Mapping[str, Any]) -> str:
    """Map Claude rate-limit status fields into provider-usage vendor states."""
    status = str(info.get("status") or "").casefold()
    overage = str(info.get("overageStatus") or "").casefold()
    combined = f"{status} {overage}"
    if any(marker in status for marker in ("reject", "blocked", "denied", "limited")):
        return "rejected"
    if any(marker in status for marker in ("warn", "approach")):
        return "warning"
    if "allowed" in status:
        return "allowed"
    if any(marker in combined for marker in ("reject", "blocked", "denied", "limited")):
        return "rejected"
    if any(marker in combined for marker in ("warn", "approach")):
        return "warning"
    return "unknown"


def is_finite_number(value: object) -> bool:
    """Return whether a JSON value is a finite numeric value."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    number = float(value)
    return number == number and number not in {float("inf"), float("-inf")}


def status_observation(
    context: UsageProbeContext,
    *,
    now: float,
    outcome: str,
    reason_code: str | None = None,
    diagnostic: str | None = None,
    account_mode: str | None = None,
    plan: str | None = None,
) -> dict[str, Any]:
    """Build and validate a status-only provider-usage observation."""
    observation = validated_status_observation(
        context,
        now=now,
        outcome=outcome,  # type: ignore[arg-type]
        reason_code=reason_code,  # type: ignore[arg-type]
        diagnostic=diagnostic,
    )
    if account_mode is None and plan is None:
        return observation
    enriched = dict(observation)
    enriched["account_mode"] = account_mode
    enriched["plan"] = plan
    try:
        return validate_observation(enriched, now=max(now, context.request_started_at))
    except (TypeError, ValueError, AttributeError):
        return observation


def _usage_window_identity(label: str) -> tuple[str, str, dict[str, Any]]:
    normalized = label_words(label)
    if "session" in normalized or ("five" in normalized and "hour" in normalized):
        return "session", "Claude session", {"kind": "product", "product": "claude"}
    model_id = _model_id_from_label(normalized)
    if model_id is not None and ("week" in normalized or "weekly" in normalized):
        return (
            f"weekly:{slugify(model_id)}",
            f"Claude weekly {label}",
            {"kind": "models", "model_ids": [model_id]},
        )
    if (
        normalized in {"week", "weekly", "seven day", "7 day"}
        or ("week" in normalized and "all" in normalized and "model" in normalized)
        or ("weekly" in normalized and "all" in normalized and "model" in normalized)
    ):
        return (
            "weekly",
            "Claude weekly all models",
            {"kind": "product", "product": "claude"},
        )
    slug = slugify(label)
    return (
        f"window:{slug}",
        f"Claude {label}",
        {"kind": "unknown", "vendor_label": label, "vendor_id": slug},
    )


def _model_id_from_label(normalized_label: str) -> str | None:
    padded = f" {normalized_label} "
    for model_id, aliases in _MODEL_LABELS:
        for alias in aliases:
            if f" {alias} " in padded:
                return model_id
    return None


def _usage_parse_diagnostic(
    unparsed_reset_expressions: list[str],
    *,
    had_non_reset_parse_error: bool,
) -> str | None:
    if unparsed_reset_expressions:
        first, *rest = unparsed_reset_expressions
        message = f'unparsed Claude usage reset expression: "{first}"'
        if rest:
            message = f"{message} (+{len(rest)} more)"
        return bounded_probe_diagnostic(message)
    if had_non_reset_parse_error:
        return bounded_probe_diagnostic("some Claude usage rows could not be parsed")
    return None


def _numeric_zero(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return float(value) == 0.0
    if isinstance(value, str):
        try:
            return float(value) == 0.0
        except ValueError:
            return False
    return False
