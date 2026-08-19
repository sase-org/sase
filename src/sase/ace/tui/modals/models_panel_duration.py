"""Duration helpers for temporary model-alias overrides."""

from __future__ import annotations

import time
from dataclasses import dataclass

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


@dataclass(frozen=True)
class RelativeOverrideDuration:
    """A finite override duration measured in seconds."""

    seconds: float


@dataclass(frozen=True)
class KeepCurrentWindow:
    """Reuse the active disable's stored expiry when flipping mode."""

    expires_at: float | None


class OverrideUntilCleared:
    """Sentinel for an override with no expiry."""


class OpenOverrideUntil:
    """Sentinel requesting the absolute-time entry popup."""


OVERRIDE_UNTIL_CLEARED = OverrideUntilCleared()
OPEN_OVERRIDE_UNTIL = OpenOverrideUntil()

type OverrideDurationResult = (
    RelativeOverrideDuration
    | OverrideUntilCleared
    | OpenOverrideUntil
    | KeepCurrentWindow
)


def _keep_current_remaining(expires_at: float | None) -> str:
    """Format the keep-current-window remaining label."""
    if expires_at is None:
        return "until cleared"
    return f"{format_remaining(expires_at - now())} left"


def _parse_override_custom(raw: str) -> OverrideDurationResult:
    try:
        seconds = parse_override_duration(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid duration: {exc}") from exc
    if seconds is None:
        return OVERRIDE_UNTIL_CLEARED
    return RelativeOverrideDuration(seconds)


class DurationPickerModal(
    DurationChoiceModal[OverrideDurationResult, DurationChoiceCancelled]
):
    """Pick how long the override should last.

    Dismisses with one of:

    - :class:`RelativeOverrideDuration` - a finite duration was chosen.
    - :class:`OverrideUntilCleared` - no expiry.
    - :class:`OpenOverrideUntil` - open the exact-time input.
    - :class:`KeepCurrentWindow` - reuse the stored expiry when flipping mode.
    - shared cancel sentinel - user cancelled.
    """

    def __init__(
        self,
        *,
        title: str = "Override Duration",
        quick_subtitle: str = "Use for quick model checks.",
        short_subtitle: str = "Keep the override through a short task.",
        hour_subtitle: str = "Cover a focused coding session.",
        two_hour_subtitle: str = "Use for a longer implementation block.",
        four_hour_subtitle: str = "Keep the override for half a day.",
        until_cleared_subtitle: str = "Persist until you remove it.",
        until_time_subtitle: str = "Choose a local clock time or date.",
        custom_placeholder: str = "e.g., 30m, 2h, 1h30m, until cleared",
        id_prefix: str = "override-duration",
        keep_current: KeepCurrentWindow | None = None,
    ) -> None:
        choices: list[DurationChoice[OverrideDurationResult]] = []
        if keep_current is not None:
            remaining = _keep_current_remaining(keep_current.expires_at)
            choices.append(
                DurationChoice(
                    key="x",
                    title=f"Keep current window ({remaining})",
                    subtitle="Flip the mode without changing the remaining window.",
                    value=keep_current,
                    tone="accent",
                )
            )
        choices.extend(
            [
                DurationChoice(
                    key="1",
                    title="15 minutes",
                    subtitle=quick_subtitle,
                    value=RelativeOverrideDuration(15 * 60.0),
                    tone="primary",
                ),
                DurationChoice(
                    key="2",
                    title="30 minutes",
                    subtitle=short_subtitle,
                    value=RelativeOverrideDuration(30 * 60.0),
                ),
                DurationChoice(
                    key="3",
                    title="1 hour",
                    subtitle=hour_subtitle,
                    value=RelativeOverrideDuration(60 * 60.0),
                ),
                DurationChoice(
                    key="4",
                    title="2 hours",
                    subtitle=two_hour_subtitle,
                    value=RelativeOverrideDuration(2 * 60 * 60.0),
                ),
                DurationChoice(
                    key="5",
                    title="4 hours",
                    subtitle=four_hour_subtitle,
                    value=RelativeOverrideDuration(4 * 60 * 60.0),
                ),
                DurationChoice(
                    key="6",
                    title="Until cleared",
                    subtitle=until_cleared_subtitle,
                    value=OVERRIDE_UNTIL_CLEARED,
                    tone="accent",
                ),
                DurationChoice(
                    key="t",
                    title="Until a specific time",
                    subtitle=until_time_subtitle,
                    value=OPEN_OVERRIDE_UNTIL,
                    tone="primary",
                ),
            ]
        )
        super().__init__(
            title=title,
            choices=choices,
            parse_custom=_parse_override_custom,
            custom_placeholder=custom_placeholder,
            cancel_result=DURATION_CHOICE_CANCELLED,
            id_prefix=id_prefix,
        )
