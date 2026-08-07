"""Normalization helpers for generic notification gate presentation fields."""

from __future__ import annotations

from datetime import datetime
import re
import unicodedata

from sase.notification_gates.models import GateError

GATE_PANEL_ACTION_DATA_KEY = "panel"
GATE_ORIGIN_AGENT_ACTION_DATA_KEY = "origin_agent"
GATE_TITLE_ACTION_DATA_KEY = "gate_title"
# Every synthetic notification-panel tab key. A gate declaring one of these
# would silently collide with the tab the panel already renders itself.
RESERVED_GATE_PANELS = frozenset(
    {"errors", "gates", "general", "hitl", "muted", "snoozed"}
)

_GATE_PANEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_MAX_GATE_PANEL_LENGTH = 32
_MAX_GATE_ORIGIN_AGENT_LENGTH = 128
_MAX_GATE_TITLE_LENGTH = 120


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


__all__ = [
    "GATE_ORIGIN_AGENT_ACTION_DATA_KEY",
    "GATE_PANEL_ACTION_DATA_KEY",
    "GATE_TITLE_ACTION_DATA_KEY",
    "RESERVED_GATE_PANELS",
    "normalize_gate_origin_agent",
    "normalize_gate_panel",
    "normalize_gate_snooze_until",
    "normalize_gate_title",
]
