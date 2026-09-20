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
from sase.config.core import current_config_token, load_config_layers
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


def _is_criterion_value(value: object) -> bool:
    return isinstance(value, str) or (
        isinstance(value, list) and all(isinstance(item, str) for item in value)
    )


def _match_problems(raw: object) -> list[str]:
    if not isinstance(raw, dict):
        return [f"match must be a mapping, not {type(raw).__name__}"]
    problems: list[str] = []
    unknown = sorted(str(key) for key in raw if key not in _MATCH_KEYS)
    if unknown:
        problems.append(
            f"unknown match criterion {', '.join(map(repr, unknown))} "
            f"(expected one of {', '.join(sorted(_MATCH_KEYS))})"
        )
    for key in sorted(_MATCH_KEYS.intersection(raw)):
        if not _is_criterion_value(raw[key]):
            # A criterion left blank would otherwise widen the rule.
            problems.append(f"match.{key} must be a string or a list of strings")
    return problems


def _rule_problems(raw: object) -> list[str]:
    """Return why ``raw`` cannot be applied as a delivery rule; empty when valid.

    A rule applies exactly as written or not at all: an unknown key, a value of
    the wrong type, or a criterion that would have to be guessed at drops the
    whole rule, because keeping it with a field stripped could make it match
    more broadly than its author wrote. The poll only has to keep such rules
    out; these reasons are what ``sase doctor`` and ``sase notify rules`` show.
    """
    if not isinstance(raw, dict):
        return [f"a rule must be a mapping, not {type(raw).__name__}"]
    problems: list[str] = []
    unknown = sorted(str(key) for key in raw if key not in _RULE_KEYS)
    if unknown:
        problems.append(
            f"unknown rule key {', '.join(map(repr, unknown))} "
            f"(expected one of {', '.join(sorted(_RULE_KEYS))})"
        )
    for key in ("name", "description", "sound"):
        if raw.get(key) is not None and not isinstance(raw[key], str):
            problems.append(f"{key} must be a string")
    if raw.get("toast") is not None and not isinstance(raw["toast"], bool):
        problems.append("toast must be true or false")
    priority = raw.get("priority")
    if priority is not None and (
        not isinstance(priority, int)
        or isinstance(priority, bool)
        or not _MIN_RULE_PRIORITY <= priority <= _MAX_RULE_PRIORITY
    ):
        problems.append(
            f"priority must be an integer from {_MIN_RULE_PRIORITY} "
            f"to {_MAX_RULE_PRIORITY}"
        )
    if "match" in raw:
        problems.extend(_match_problems(raw["match"]))
    return problems


def _sanitize_rule(raw: object) -> dict[str, Any] | None:
    """Return the wire form of one configured rule, or ``None`` for stored junk."""
    if not isinstance(raw, dict) or _rule_problems(raw):
        return None
    rule = {
        key: raw[key]
        for key in ("name", "description", "sound", "toast", "priority")
        if raw.get(key) is not None
    }
    if "match" in raw:
        rule["match"] = {
            key: value if isinstance(value, str) else list(value)
            for key, value in raw["match"].items()
        }
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


@dataclass(frozen=True)
class ConfiguredNotificationRule:
    """One ``ace.notification_rules`` entry, with the config layer it came from.

    ``rule`` is the wire form the core evaluates and ``index`` its position in
    the list :func:`notification_delivery_rules` returns; both are ``None`` for
    an entry that was dropped, whose ``problems`` say why.
    """

    layer: str
    layer_index: int
    raw: object
    rule: dict[str, Any] | None
    index: int | None
    label: str
    problems: tuple[str, ...] = ()

    @property
    def priority(self) -> int:
        return int((self.rule or {}).get("priority", 0))


def notification_rule_label(rule: dict[str, Any], index: int) -> str:
    """Return the name the core reports for ``rule`` at ``index`` in its rule list."""
    return rule.get("name") or f"rule[{index}]"


def _merged_rule_entries() -> list[tuple[str, int, object]]:
    """Return every merged ``ace.notification_rules`` entry with its layer.

    Replays the list merge on the unmerged layers: a ``replace`` layer (the user
    file) discards what came before it, a ``concatenate`` layer appends, and a
    layer that sets the key to something other than a list overrides the list
    outright. Layers are visited in merge order, so the result is the list the
    core is handed, before malformed entries are dropped.
    """
    entries: list[tuple[str, int, object]] = []
    for layer in load_config_layers():
        if "ace" not in layer.data:
            continue
        ace = layer.data["ace"]
        if not isinstance(ace, dict):
            entries = []
            continue
        if "notification_rules" not in ace:
            continue
        raw = ace["notification_rules"]
        if not isinstance(raw, list):
            entries = []
            continue
        contributed = [(layer.name, index, entry) for index, entry in enumerate(raw)]
        if layer.list_strategy == "replace":
            entries = contributed
        else:
            entries = [*entries, *contributed]
    return entries


def configured_notification_rules() -> tuple[ConfiguredNotificationRule, ...]:
    """Return every merged rule entry, in list order, with its source layer.

    Reads the unmerged config layers rather than the cached merged config, so
    it is for diagnostics (``sase notify rules``, ``sase doctor``), not the
    poll. Entries that :func:`notification_delivery_rules` skips are included
    with their ``problems``; the rest carry the ``index`` and ``label`` the core
    reports back in a resolved delivery.
    """
    configured: list[ConfiguredNotificationRule] = []
    next_index = 0
    for layer_name, layer_index, raw in _merged_rule_entries():
        rule = _sanitize_rule(raw)
        if rule is None:
            named = raw.get("name") if isinstance(raw, dict) else None
            configured.append(
                ConfiguredNotificationRule(
                    layer=layer_name,
                    layer_index=layer_index,
                    raw=raw,
                    rule=None,
                    index=None,
                    label=named if isinstance(named, str) and named else "(ignored)",
                    problems=tuple(_rule_problems(raw)),
                )
            )
            continue
        configured.append(
            ConfiguredNotificationRule(
                layer=layer_name,
                layer_index=layer_index,
                raw=raw,
                rule=rule,
                index=next_index,
                label=notification_rule_label(rule, next_index),
            )
        )
        next_index += 1
    return tuple(configured)


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
    "ConfiguredNotificationRule",
    "NotificationDelivery",
    "NotificationSound",
    "configured_notification_rules",
    "notification_delivery_rules",
    "notification_rule_label",
    "resolve_notification_deliveries",
]
