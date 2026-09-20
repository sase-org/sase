"""Client-side notification delivery: which arrivals toast and how they sound.

``ace.notification_rules`` is an ordered list of rules that each match a
notification by tab, sender, action, tag, title, or note text and set whether a
TUI toast is shown and how the arrival is announced. The matcher lives in the
Rust core; this module reads the configured rules, reduces them to the core's
wire shape, and resolves a batch of notifications through one binding call.

Delivery is an announcement decision only. A rule never changes whether a
notification is created, stored, read, muted, or snoozed, and with no rules
configured every notification resolves to today's behavior: toast and bell.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sase.config import load_merged_config
from sase.config.core import current_config_token
from sase.core.notification_store_facade import (
    resolve_notification_deliveries as resolve_wire_deliveries,
)
from sase.core.notification_store_wire import (
    NotificationDeliveryWire,
    NotificationSoundWire,
)
from sase.notifications.models import Notification

SOUND_BELL = "bell"
SOUND_NONE = "none"
SOUND_FILE = "file"

_RULE_KEYS = frozenset({"name", "description", "priority", "match", "toast", "sound"})
_MATCH_KEYS = frozenset({"tab", "sender", "action", "tags", "title", "note"})
# Mirrors the ``ace.notification_rules[].priority`` bounds in the config schema.
_MIN_RULE_PRIORITY = -1000
_MAX_RULE_PRIORITY = 1000


@dataclass(frozen=True)
class NotificationSound:
    """How an arrival is announced: ``bell``, ``none``, or a ``file`` at ``path``."""

    kind: str
    path: str | None = None


@dataclass(frozen=True)
class NotificationDelivery:
    """Whether one notification toasts and how it sounds, plus what decided that.

    ``toast_rule`` and ``sound_rule`` name the deciding rule (its ``name``, else
    ``rule[<index>]`` counting :func:`notification_delivery_rules`) and are
    ``None`` when the built-in default applied.
    """

    toast: bool
    sound: NotificationSound
    toast_rule: str | None = None
    sound_rule: str | None = None


# What every notification did before rules existed; the core resolves an empty
# rule list to exactly this.
DEFAULT_NOTIFICATION_DELIVERY = NotificationDelivery(
    toast=True, sound=NotificationSound(kind=SOUND_BELL)
)


def _ace_config() -> dict[str, Any]:
    try:
        config = load_merged_config()
    except Exception:
        return {}
    if not isinstance(config, dict):
        return {}
    ace = config.get("ace", {})
    return ace if isinstance(ace, dict) else {}


def _sanitize_match(raw: object) -> dict[str, Any] | None:
    """Return the wire form of a ``match`` block, or ``None`` for stored junk."""
    if not isinstance(raw, dict) or not set(raw) <= _MATCH_KEYS:
        return None
    match: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            match[key] = value
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            match[key] = list(value)
        else:
            # A criterion left blank would otherwise widen the rule.
            return None
    return match


def _sanitize_rule(raw: object) -> dict[str, Any] | None:
    """Return the wire form of one configured rule, or ``None`` for stored junk.

    A rule applies exactly as written or not at all: an unknown key, a value of
    the wrong type, or a criterion that would have to be guessed at drops the
    whole rule, because keeping it with a field stripped could make it match
    more broadly than its author wrote. ``sase doctor`` reports the dropped
    rules; this path only has to keep them out of the poll.
    """
    if not isinstance(raw, dict) or not set(raw) <= _RULE_KEYS:
        return None
    rule: dict[str, Any] = {}
    for key in ("name", "description", "sound"):
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            return None
        rule[key] = value
    toast = raw.get("toast")
    if toast is not None:
        if not isinstance(toast, bool):
            return None
        rule["toast"] = toast
    priority = raw.get("priority")
    if priority is not None:
        if (
            not isinstance(priority, int)
            or isinstance(priority, bool)
            or not _MIN_RULE_PRIORITY <= priority <= _MAX_RULE_PRIORITY
        ):
            return None
        rule["priority"] = priority
    if "match" in raw:
        match = _sanitize_match(raw["match"])
        if match is None:
            return None
        rule["match"] = match
    return rule


@lru_cache(maxsize=1)
def _delivery_rules_for_token(_token: tuple[Any, ...]) -> tuple[dict[str, Any], ...]:
    """Read and sanitize ``ace.notification_rules`` once per config token."""
    raw = _ace_config().get("notification_rules", [])
    if not isinstance(raw, list):
        return ()
    rules = (_sanitize_rule(entry) for entry in raw)
    return tuple(rule for rule in rules if rule is not None)


def notification_delivery_rules() -> tuple[dict[str, Any], ...]:
    """Return the configured delivery rules in the core's wire shape.

    Malformed entries are skipped rather than raised, so a bad rule can never
    break a poll or render; the surviving list is what the core resolves, and
    its positions are what an unnamed rule's ``rule[<index>]`` label counts.
    The result is cached on the config token, so a render or poll pays one
    config read. The rule dicts are shared: callers must not mutate them.
    """
    return _delivery_rules_for_token(current_config_token())


def _sound_from_wire(wire: NotificationSoundWire) -> NotificationSound:
    return NotificationSound(kind=wire.kind, path=wire.path)


def _delivery_from_wire(wire: NotificationDeliveryWire) -> NotificationDelivery:
    return NotificationDelivery(
        toast=wire.toast,
        sound=_sound_from_wire(wire.sound),
        toast_rule=wire.toast_rule,
        sound_rule=wire.sound_rule,
    )


def resolve_notification_deliveries(
    notifications: Sequence[Notification],
) -> list[NotificationDelivery]:
    """Resolve the delivery of every notification, in input order.

    One binding call resolves the whole batch, and none is made when there is
    nothing to resolve or no rules are configured. Performs a config read and
    an FFI call, so async callers should run it off the event loop.
    """
    if not notifications:
        return []
    rules = notification_delivery_rules()
    if not rules:
        return [DEFAULT_NOTIFICATION_DELIVERY] * len(notifications)
    return [
        _delivery_from_wire(wire)
        for wire in resolve_wire_deliveries(rules, notifications)
    ]


__all__ = [
    "DEFAULT_NOTIFICATION_DELIVERY",
    "SOUND_BELL",
    "SOUND_FILE",
    "SOUND_NONE",
    "NotificationDelivery",
    "NotificationSound",
    "notification_delivery_rules",
    "resolve_notification_deliveries",
]
