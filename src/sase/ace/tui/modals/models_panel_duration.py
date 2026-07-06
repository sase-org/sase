"""Duration helpers for temporary model-alias overrides."""

from __future__ import annotations

import time

from sase.llm_provider import parse_override_duration

from .duration_choice_modal import (
    DURATION_CHOICE_CANCELLED,
    DurationChoice,
    DurationChoiceCancelled,
    DurationChoiceModal,
)


def now() -> float:
    """Return the current wall-clock time (indirection lets tests pin it)."""
    return time.time()


def format_remaining(seconds: float) -> str:
    """Format an integer-second remaining duration as ``"1h30m"`` etc."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs and not hours and not minutes:
        parts.append(f"{secs}s")
    return "".join(parts) or "0s"


def format_duration_chosen(seconds: float | None) -> str:
    """Render the chosen duration for the success notification."""
    if seconds is None:
        return "until cleared"
    return format_remaining(seconds)


def _parse_override_custom(raw: str) -> float | None:
    try:
        return parse_override_duration(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid duration: {exc}") from exc


class DurationPickerModal(DurationChoiceModal[float | None, DurationChoiceCancelled]):
    """Pick how long the override should last.

    Dismisses with one of:

    - ``float`` (seconds) - a finite duration was chosen.
    - ``None`` - "Until cleared" (no expiry).
    - shared cancel sentinel - user cancelled.
    """

    def __init__(self) -> None:
        super().__init__(
            title="Override Duration",
            choices=[
                DurationChoice(
                    key="1",
                    title="15 minutes",
                    subtitle="Use for quick model checks.",
                    value=15 * 60.0,
                    tone="primary",
                ),
                DurationChoice(
                    key="2",
                    title="30 minutes",
                    subtitle="Keep the override through a short task.",
                    value=30 * 60.0,
                ),
                DurationChoice(
                    key="3",
                    title="1 hour",
                    subtitle="Cover a focused coding session.",
                    value=60 * 60.0,
                ),
                DurationChoice(
                    key="4",
                    title="2 hours",
                    subtitle="Use for a longer implementation block.",
                    value=2 * 60 * 60.0,
                ),
                DurationChoice(
                    key="5",
                    title="4 hours",
                    subtitle="Keep the override for half a day.",
                    value=4 * 60 * 60.0,
                ),
                DurationChoice(
                    key="6",
                    title="Until cleared",
                    subtitle="Persist until you remove it.",
                    value=None,
                    tone="accent",
                ),
            ],
            parse_custom=_parse_override_custom,
            custom_placeholder="e.g., 30m, 2h, 1h30m, until cleared",
            cancel_result=DURATION_CHOICE_CANCELLED,
            id_prefix="override-duration",
        )
