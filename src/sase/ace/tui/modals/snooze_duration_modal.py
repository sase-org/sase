"""Snooze duration picker modal for the notification panel."""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.core.time import get_timezone
from sase.xprompt._directive_time import parse_duration

from .duration_choice_modal import DurationChoice, DurationChoiceModal


_PRESET_DELTAS: dict[str, timedelta] = {
    "1": timedelta(minutes=15),
    "2": timedelta(hours=1),
    "3": timedelta(hours=4),
}


def _tomorrow_morning(now: datetime | None = None) -> datetime:
    """Compute the next 09:00 local time strictly more than a day away.

    If now is at or before 09:00 on day D, returns 09:00 on D+1.
    If now is after 09:00 on day D, also returns 09:00 on D+1.
    """
    tz = get_timezone()
    if now is None:
        now = datetime.now(tz)
    target = now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return target


def _parse_snooze_custom(raw: str) -> timedelta:
    seconds = parse_duration(raw)
    if seconds is None or seconds <= 0:
        raise ValueError("Invalid duration - try '30m', '2h', '1h30m'.")
    return timedelta(seconds=seconds)


class SnoozeDurationModal(DurationChoiceModal[timedelta | datetime, None]):
    """Quick picker for choosing a snooze duration.

    Returns a ``timedelta`` for relative presets, a ``datetime`` for
    absolute presets (``"Tomorrow morning"``), or ``None`` on cancel.
    """

    def __init__(self) -> None:
        super().__init__(
            title="Snooze Notification",
            choices=[
                DurationChoice(
                    key="1",
                    title="15 minutes",
                    subtitle="Pause this notification briefly.",
                    value=_PRESET_DELTAS["1"],
                    tone="primary",
                ),
                DurationChoice(
                    key="2",
                    title="1 hour",
                    subtitle="Bring it back later today.",
                    value=_PRESET_DELTAS["2"],
                ),
                DurationChoice(
                    key="3",
                    title="4 hours",
                    subtitle="Clear the next work block.",
                    value=_PRESET_DELTAS["3"],
                ),
                DurationChoice(
                    key="4",
                    title="Tomorrow morning",
                    subtitle="Return at 9:00 AM local time.",
                    value=_tomorrow_morning,
                    tone="accent",
                ),
            ],
            parse_custom=_parse_snooze_custom,
            custom_placeholder="e.g., 30m, 2h, 1h30m",
            id_prefix="snooze",
            cancel_result=None,
        )
