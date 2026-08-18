"""Normalization helpers for generic notification gate presentation fields."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import re
import unicodedata

from sase.notification_gates.models import GateError
from sase.notification_gates.model_validation import validate_color, validate_icon

GATE_CHIP_COLOR_ACTION_DATA_KEY = "gate_chip_color"
GATE_CHIP_GLYPH_ACTION_DATA_KEY = "gate_chip_glyph"
GATE_CHIP_LABEL_ACTION_DATA_KEY = "gate_chip_label"
GATE_PANEL_ACTION_DATA_KEY = "panel"
GATE_PANEL_ICON_ACTION_DATA_KEY = "panel_icon"
GATE_ORIGIN_AGENT_ACTION_DATA_KEY = "origin_agent"
GATE_TITLE_ACTION_DATA_KEY = "gate_title"
# Every synthetic notification-panel tab key. A gate declaring one of these
# would silently collide with the tab the panel already renders itself.
RESERVED_GATE_PANELS = frozenset(
    {"errors", "gates", "general", "hitl", "muted", "snoozed"}
)

_GATE_PANEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_MAX_GATE_CHIP_LABEL_LENGTH = 32
_MAX_GATE_PANEL_LENGTH = 32
_MAX_GATE_ORIGIN_AGENT_LENGTH = 128
_MAX_GATE_TITLE_LENGTH = 120


@dataclass(frozen=True)
class GateChip:
    """Sender-declared subject chip: one glyph, a short label, optional accent."""

    glyph: str
    label: str
    color: str | None = None


def normalize_gate_panel(value: object) -> str | None:
    """Return a canonical notification panel name, if one was declared."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid_panel(value, "must be a string")
    panel = value.strip().lower()
    if len(panel) > _MAX_GATE_PANEL_LENGTH:
        raise _invalid_panel(
            value,
            f"must be at most {_MAX_GATE_PANEL_LENGTH} characters",
        )
    if panel in RESERVED_GATE_PANELS or panel.startswith("__"):
        reserved = ", ".join(sorted(RESERVED_GATE_PANELS))
        raise _invalid_panel(
            value,
            f"is reserved; reserved panels are: {reserved}, and names beginning "
            "with '__'",
        )
    if not _GATE_PANEL_RE.fullmatch(panel):
        raise _invalid_panel(value, "must match [a-z0-9][a-z0-9_-]*")
    return panel


def normalize_gate_panel_icon(value: object) -> str | None:
    """Return the glyph a gate declares for its notification-panel tab.

    The row's own ``presentation.icon`` cannot stand in for this: rows sharing a
    panel legitimately carry different icons, so donating one would make the
    tab's glyph flip with whichever row arrived most recently.
    """
    if value is None:
        return None
    try:
        return validate_icon(value, "presentation.panel_icon")
    except GateError as exc:
        raise GateError(
            "invalid_presentation",
            "presentation.panel_icon",
            f"invalid panel icon {value!r}: must be a single emoji or glyph",
        ) from exc


def normalize_gate_snooze_until(value: object) -> str | None:
    """Return the wake time a gate declares it should be born snoozed until.

    A producer that already knows its gate is not actionable until a future
    instant declares that instant here, so gate creation stays one atomic
    append: there is no window in which the notification is briefly unread.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid_snooze_until(value, "must be a string")
    text = value.strip()
    if not text:
        raise _invalid_snooze_until(value, "must be non-empty")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid_snooze_until(
            value, f"must be an ISO-8601 timestamp with an offset ({exc})"
        ) from exc
    if parsed.tzinfo is None:
        raise _invalid_snooze_until(
            value, "must be an ISO-8601 timestamp with an offset"
        )
    return text


def normalize_gate_origin_agent(value: object) -> str | None:
    """Return the stripped agent attribution declared by a gate producer."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid_origin_agent(value, "must be a string")
    origin_agent = value.strip()
    if not origin_agent:
        raise _invalid_origin_agent(value, "must be non-empty")
    if len(origin_agent) > _MAX_GATE_ORIGIN_AGENT_LENGTH:
        raise _invalid_origin_agent(
            value,
            f"must be at most {_MAX_GATE_ORIGIN_AGENT_LENGTH} characters",
        )
    if any(unicodedata.category(character) == "Cc" for character in origin_agent):
        raise _invalid_origin_agent(value, "must not contain control characters")
    return origin_agent


def normalize_gate_title(value: object) -> str | None:
    """Return the stripped one-line decision headline declared by a gate."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid_title(value, "must be a string")
    title = value.strip()
    if not title:
        raise _invalid_title(value, "must be non-empty")
    if len(title) > _MAX_GATE_TITLE_LENGTH:
        raise _invalid_title(
            value, f"must be at most {_MAX_GATE_TITLE_LENGTH} characters"
        )
    if "\n" in title:
        raise _invalid_title(value, "must be a single line")
    if any(unicodedata.category(character) == "Cc" for character in title):
        raise _invalid_title(value, "must not contain control characters")
    return title


def normalize_gate_chip(value: object) -> GateChip | None:
    """Return a canonical subject chip, if one was declared."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _invalid_chip(value, "must be an object")
    glyph = _normalize_chip_glyph(value.get("glyph"), declared=value)
    if glyph is None:
        raise _invalid_chip(value, "glyph is required")
    label = _normalize_chip_label(value.get("label"), declared=value)
    if label is None:
        raise _invalid_chip(value, "label is required")
    return GateChip(
        glyph=glyph,
        label=label,
        color=_normalize_chip_color(value.get("color"), declared=value),
    )


def gate_chip_from_action_data(action_data: object) -> GateChip | None:
    """Return a usable chip from stored notification ``action_data``, or None.

    This is the zero-I/O render-path reader: it never raises. A missing or
    malformed glyph or label drops the chip; a stored colour that is not
    ``#RRGGBB`` is ignored so the glyph and label still render.
    """
    if not isinstance(action_data, Mapping):
        return None
    try:
        glyph = _normalize_chip_glyph(action_data.get(GATE_CHIP_GLYPH_ACTION_DATA_KEY))
        label = _normalize_chip_label(action_data.get(GATE_CHIP_LABEL_ACTION_DATA_KEY))
    except (AttributeError, GateError, TypeError):
        return None
    if glyph is None or label is None:
        return None
    color: str | None = None
    raw_color = action_data.get(GATE_CHIP_COLOR_ACTION_DATA_KEY)
    if raw_color is not None:
        try:
            color = _normalize_chip_color(raw_color)
        except (AttributeError, GateError, TypeError):
            color = None
    return GateChip(glyph=glyph, label=label, color=color)


def _invalid_panel(value: object, reason: str) -> GateError:
    return GateError(
        "invalid_presentation",
        "presentation.panel",
        f"invalid panel {value!r}: {reason}",
    )


def _invalid_snooze_until(value: object, reason: str) -> GateError:
    return GateError(
        "invalid_presentation",
        "presentation.snooze_until",
        f"invalid snooze_until {value!r}: {reason}",
    )


def _invalid_origin_agent(value: object, reason: str) -> GateError:
    return GateError(
        "invalid_presentation",
        "presentation.origin_agent",
        f"invalid origin agent {value!r}: {reason}",
    )


def _invalid_title(value: object, reason: str) -> GateError:
    return GateError(
        "invalid_presentation",
        "presentation.title",
        f"invalid title {value!r}: {reason}",
    )


def _invalid_chip(value: object, reason: str) -> GateError:
    return GateError(
        "invalid_presentation",
        "presentation.chip",
        f"invalid chip {value!r}: {reason}",
    )


def _normalize_chip_glyph(
    value: object, *, declared: object | None = None
) -> str | None:
    shown = value if declared is None else declared
    try:
        return validate_icon(value, "presentation.chip")
    except GateError as exc:
        raise _invalid_chip(shown, "glyph must be a single emoji or glyph") from exc


def _normalize_chip_label(
    value: object, *, declared: object | None = None
) -> str | None:
    shown = value if declared is None else declared
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid_chip(shown, "label must be a string")
    label = value.strip()
    if not label:
        raise _invalid_chip(shown, "label must be non-empty")
    if len(label) > _MAX_GATE_CHIP_LABEL_LENGTH:
        raise _invalid_chip(
            shown,
            f"label must be at most {_MAX_GATE_CHIP_LABEL_LENGTH} characters",
        )
    if "\n" in label:
        raise _invalid_chip(shown, "label must be a single line")
    if any(unicodedata.category(character) == "Cc" for character in label):
        raise _invalid_chip(shown, "label must not contain control characters")
    return label


def _normalize_chip_color(
    value: object, *, declared: object | None = None
) -> str | None:
    shown = value if declared is None else declared
    try:
        return validate_color(value, "presentation.chip")
    except GateError as exc:
        raise _invalid_chip(shown, "color must be an '#RRGGBB' hex color") from exc


__all__ = [
    "GATE_CHIP_COLOR_ACTION_DATA_KEY",
    "GATE_CHIP_GLYPH_ACTION_DATA_KEY",
    "GATE_CHIP_LABEL_ACTION_DATA_KEY",
    "GATE_ORIGIN_AGENT_ACTION_DATA_KEY",
    "GATE_PANEL_ACTION_DATA_KEY",
    "GATE_PANEL_ICON_ACTION_DATA_KEY",
    "GATE_TITLE_ACTION_DATA_KEY",
    "RESERVED_GATE_PANELS",
    "GateChip",
    "gate_chip_from_action_data",
    "normalize_gate_chip",
    "normalize_gate_origin_agent",
    "normalize_gate_panel",
    "normalize_gate_panel_icon",
    "normalize_gate_snooze_until",
    "normalize_gate_title",
]
