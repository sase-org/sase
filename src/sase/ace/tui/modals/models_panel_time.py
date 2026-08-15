"""Timezone-aware absolute-time input for Models-panel overrides."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from sase.core.time import get_timezone

_CLOCK_12_RE = re.compile(
    r"^(?P<hour>0?[1-9]|1[0-2])(?::?(?P<minute>[0-5]\d))?\s*"
    r"(?P<period>[ap])\.?m\.?$",
    re.IGNORECASE,
)
_CLOCK_24_RE = re.compile(r"^(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)$")
_CLOCK_COMPACT_RE = re.compile(r"^(?P<hour>[01]\d|2[0-3])(?P<minute>[0-5]\d)$")
_DATE_TIME_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})[ T](?P<clock>.+)$")


class OverrideUntilBack:
    """Sentinel returned when the user goes back to duration choices."""


OVERRIDE_UNTIL_BACK = OverrideUntilBack()


@dataclass(frozen=True)
class ResolvedOverrideUntil:
    """An absolute override target resolved in the configured timezone."""

    target: datetime
    expires_at: float
    target_display: str
    notification_display: str
    remaining_display: str
    timezone_display: str

    @property
    def preview(self) -> str:
        """Return the two-line confirmation shown in the modal."""
        return (
            f"{self.target_display}\n"
            f"in {self.remaining_display}  |  {self.timezone_display}"
        )


def _clock_now(timezone: tzinfo) -> datetime:
    return datetime.now(timezone)


def _timezone_name(timezone: tzinfo, reference: datetime) -> str:
    return getattr(timezone, "key", None) or reference.tzname() or "local timezone"


def _parse_clock(raw: str) -> time:
    token = raw.strip()
    match = _CLOCK_12_RE.fullmatch(token)
    if match:
        hour = int(match.group("hour")) % 12
        if match.group("period").lower() == "p":
            hour += 12
        return time(hour, int(match.group("minute") or "0"))

    match = _CLOCK_24_RE.fullmatch(token) or _CLOCK_COMPACT_RE.fullmatch(token)
    if match:
        return time(int(match.group("hour")), int(match.group("minute")))

    raise ValueError("Use 5pm, 17:30, 1730, tomorrow 9am, or YYYY-MM-DD 09:00.")


def _valid_local_candidates(wall: datetime, timezone: tzinfo) -> list[datetime]:
    """Return real instants represented by a naive configured-zone wall time."""
    candidates: list[datetime] = []
    seen_timestamps: set[float] = set()
    for fold in (0, 1):
        candidate = wall.replace(tzinfo=timezone, fold=fold)
        round_trip = candidate.astimezone(UTC).astimezone(timezone)
        if round_trip.replace(tzinfo=None) != wall:
            continue
        timestamp = candidate.timestamp()
        if timestamp not in seen_timestamps:
            candidates.append(candidate)
            seen_timestamps.add(timestamp)
    return candidates


def _offset_text(value: datetime) -> str:
    compact = value.strftime("%z")
    return f"{compact[:3]}:{compact[3:]}"


def _localize_wall_time(wall: datetime, timezone: tzinfo) -> datetime:
    candidates = _valid_local_candidates(wall, timezone)
    zone_name = _timezone_name(timezone, wall.replace(tzinfo=timezone))
    if not candidates:
        raise ValueError(
            f"That local time does not exist in {zone_name} "
            "(daylight-saving transition)."
        )
    if len(candidates) > 1:
        offsets = " or ".join(_offset_text(candidate) for candidate in candidates)
        raise ValueError(
            f"That local time occurs twice in {zone_name}; "
            f"use an offset-qualified ISO time ({offsets})."
        )
    return candidates[0]


def _format_day(value: datetime, now: datetime) -> str:
    day = _format_calendar_day(value, include_year=value.year != now.year)
    if value.date() == now.date():
        return f"today, {day}"
    if value.date() == now.date() + timedelta(days=1):
        return f"tomorrow, {day}"
    return day


def _format_calendar_day(value: datetime, *, include_year: bool) -> str:
    day = f"{value:%a %b} {value.day}"
    if include_year:
        day = f"{day}, {value.year}"
    return day


def _format_clock(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def _format_remaining(seconds: float) -> str:
    total_minutes = max(0, int(seconds) // 60)
    if total_minutes == 0:
        return "<1m"
    days, rem_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rem_minutes, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes and len(parts) < 2:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def _resolve_override_until(
    value: str,
    *,
    timezone: tzinfo | None = None,
    clock: Callable[[tzinfo], datetime] = _clock_now,
) -> ResolvedOverrideUntil:
    """Resolve a friendly local-time value to one exact future instant.

    Undated clocks resolve to their next occurrence. Explicit ``today`` and
    ISO-date targets must themselves be in the future. Offset-qualified ISO
    values are treated as exact instants and converted to the configured zone
    for confirmation.
    """
    token = value.strip()
    if not token:
        raise ValueError("Enter a local time, such as 5pm or tomorrow 09:00.")

    configured_timezone = timezone or get_timezone()
    now = clock(configured_timezone)
    if now.tzinfo is None:
        now = now.replace(tzinfo=configured_timezone)
    else:
        now = now.astimezone(configured_timezone)

    # Offset-qualified ISO input identifies an exact occurrence, including
    # either side of an ambiguous fall-back wall time.
    iso_match = _DATE_TIME_RE.fullmatch(token)
    if iso_match:
        try:
            exact = datetime.fromisoformat(token.replace("Z", "+00:00"))
        except ValueError:
            exact = None
        if exact is not None and exact.tzinfo is not None:
            target = exact.astimezone(configured_timezone)
            if target.timestamp() <= now.timestamp():
                raise ValueError("That time is not in the future.")
            return _resolved(target, now, configured_timezone)

    lowered = token.lower()
    day_mode: str | None = None
    clock_token = token
    for prefix in ("today", "tomorrow"):
        if lowered == prefix or lowered.startswith(f"{prefix} "):
            day_mode = prefix
            clock_token = token[len(prefix) :].strip()
            break

    explicit_date: date | None = None
    if day_mode is None:
        match = _DATE_TIME_RE.fullmatch(token)
        if match:
            try:
                explicit_date = date.fromisoformat(match.group("date"))
            except ValueError as exc:
                raise ValueError("That calendar date is invalid.") from exc
            clock_token = match.group("clock")

    clock_value = _parse_clock(clock_token)
    if explicit_date is not None:
        target_date = explicit_date
    elif day_mode == "tomorrow":
        target_date = now.date() + timedelta(days=1)
    else:
        target_date = now.date()

    wall = datetime.combine(target_date, clock_value)
    target = _localize_wall_time(wall, configured_timezone)

    if (
        day_mode is None
        and explicit_date is None
        and target.timestamp() <= now.timestamp()
    ):
        wall += timedelta(days=1)
        target = _localize_wall_time(wall, configured_timezone)
    elif target.timestamp() <= now.timestamp():
        raise ValueError("That time is not in the future.")

    return _resolved(target, now, configured_timezone)


def _resolved(
    target: datetime,
    now: datetime,
    timezone: tzinfo,
) -> ResolvedOverrideUntil:
    timezone_display = _timezone_name(timezone, target)
    target_display = (
        f"Ends {_format_day(target, now)} at {_format_clock(target)} "
        f"{target.tzname() or ''}"
    ).rstrip()
    return ResolvedOverrideUntil(
        target=target,
        expires_at=target.timestamp(),
        target_display=target_display,
        notification_display=(
            f"{_format_calendar_day(target, include_year=target.year != now.year)}, "
            f"{_format_clock(target)} {target.tzname() or ''}"
        ).rstrip(),
        remaining_display=_format_remaining(target.timestamp() - now.timestamp()),
        timezone_display=timezone_display,
    )


class OverrideUntilModal(ModalScreen[ResolvedOverrideUntil | OverrideUntilBack]):
    """Enter and confirm an exact override end in the configured timezone."""

    BINDINGS = [
        ("escape", "back", "Back"),
    ]

    def __init__(
        self,
        *,
        timezone: tzinfo | None = None,
        clock: Callable[[tzinfo], datetime] = _clock_now,
        title: str = "Override Until",
        submit_label: str = "Set override",
    ) -> None:
        super().__init__()
        self._timezone = timezone or get_timezone()
        self._clock = clock
        self._title = title
        self._submit_label = submit_label
        self._resolved_value: ResolvedOverrideUntil | None = None

    def compose(self) -> ComposeResult:
        with Container(id="override-until-container"):
            yield Label(self._title, id="override-until-title")
            with Horizontal(id="override-until-field"):
                yield Label("Time", id="override-until-field-label")
                yield Input(
                    placeholder="5pm, tomorrow 09:00, or 2026-07-12 09:00",
                    id="override-until-input",
                )
            yield Static("", id="override-until-preview", classes="until-neutral")
            yield Static(
                f"[bold]enter[/] {self._submit_label}   |   [bold]esc[/] Back",
                id="override-until-footer",
            )

    def on_mount(self) -> None:
        self._show_neutral()
        self.query_one("#override-until-input", Input).focus()

    def _show_neutral(self) -> None:
        timezone_name = _timezone_name(
            self._timezone,
            self._clock(self._timezone),
        )
        self._set_preview(
            f"Enter a local clock time or date.\nTimezone: {timezone_name}",
            "until-neutral",
        )
        self._resolved_value = None

    def _set_preview(self, message: str, css_class: str) -> None:
        preview = self.query_one("#override-until-preview", Static)
        preview.update(message)
        preview.remove_class("until-neutral", "until-valid", "until-error")
        preview.add_class(css_class)

    def _refresh_preview(self, value: str) -> None:
        if not value.strip():
            self._show_neutral()
            return
        try:
            resolved = _resolve_override_until(
                value,
                timezone=self._timezone,
                clock=self._clock,
            )
        except ValueError as exc:
            self._resolved_value = None
            self._set_preview(str(exc), "until-error")
            return
        self._resolved_value = resolved
        self._set_preview(resolved.preview, "until-valid")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "override-until-input":
            self._refresh_preview(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "override-until-input":
            return
        event.stop()
        self._refresh_preview(event.value)
        if self._resolved_value is None:
            event.input.focus()
            return
        self.dismiss(self._resolved_value)

    def action_back(self) -> None:
        self.dismiss(OVERRIDE_UNTIL_BACK)


__all__ = [
    "OVERRIDE_UNTIL_BACK",
    "OverrideUntilBack",
    "OverrideUntilModal",
    "ResolvedOverrideUntil",
]
