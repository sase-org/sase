"""``sase notify rules`` — show delivery rules and explain how a row is delivered."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from rich.console import Console
from rich.text import Text

from sase.core.notification_store_facade import classify_notification_tabs
from sase.notifications.delivery import (
    DEFAULT_NOTIFICATION_DELIVERY,
    SOUND_FILE,
    ConfiguredNotificationRule,
    NotificationDelivery,
    NotificationSound,
    configured_notification_rules,
    notification_delivery_rules,
    notification_rule_label,
    resolve_notification_deliveries,
)
from sase.notifications.models import Notification
from sase.notifications.store import read_current_notification_snapshot

_CRITERIA_ORDER = ("tab", "sender", "action", "tags", "title", "note")
_MERGED_LAYER = "merged"


def handle_notify_rules(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Print the merged delivery rules, or explain one notification's delivery."""
    out = console or Console(highlight=False)
    try:
        applied, ignored = _load_rules()
    except Exception as exc:
        print(
            f"sase notify rules: cannot read notification rules: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    explain: str | None = getattr(args, "explain", None)
    as_json = bool(getattr(args, "json", False))
    if explain is None:
        if as_json:
            _print_json(_rules_json(applied, ignored))
        else:
            _print_rules(out, applied, ignored)
        return

    notification = _find_notification(explain)
    try:
        tab = classify_notification_tabs([notification]).row_tab_keys.get(
            notification.id, ""
        )
        delivery = resolve_notification_deliveries([notification])[0]
    except Exception as exc:
        print(
            f"sase notify rules: cannot resolve delivery: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    if as_json:
        _print_json(_explain_json(notification, tab, delivery, applied))
    else:
        _print_explanation(out, notification, tab, delivery, applied)


def _load_rules() -> tuple[
    list[ConfiguredNotificationRule], list[ConfiguredNotificationRule]
]:
    """Return the applied rules in list order plus the entries that were dropped."""
    configured = configured_notification_rules()
    applied = [entry for entry in configured if entry.rule is not None]
    ignored = [entry for entry in configured if entry.rule is None]
    polled = notification_delivery_rules()
    if [entry.rule for entry in applied] != list(polled):
        # The layer replay disagrees with the merged config the poll reads, so
        # trust the poll's rules and give up on saying which layer each is from.
        applied = [
            ConfiguredNotificationRule(
                layer=_MERGED_LAYER,
                layer_index=index,
                raw=rule,
                rule=rule,
                index=index,
                label=notification_rule_label(rule, index),
            )
            for index, rule in enumerate(polled)
        ]
    return applied, ignored


def _evaluation_order(
    applied: Sequence[ConfiguredNotificationRule],
) -> list[ConfiguredNotificationRule]:
    """Order rules as the core consults them: priority descending, then list order."""
    return sorted(applied, key=lambda entry: (-entry.priority, entry.index or 0))


def _find_notification(ref: str) -> Notification:
    """Return the notification for an id or unique prefix, or exit with an error."""
    try:
        rows = list(
            read_current_notification_snapshot(include_dismissed=True).notifications
        )
    except Exception as exc:
        print(f"sase notify rules: cannot read notifications: {exc}", file=sys.stderr)
        sys.exit(1)
    matches = [row for row in rows if row.id == ref] or [
        row for row in rows if row.id.startswith(ref)
    ]
    if not matches:
        print(f"sase notify rules: notification not found: {ref}", file=sys.stderr)
        sys.exit(2)
    if len(matches) > 1:
        print(
            f"sase notify rules: ambiguous notification id prefix: {ref} "
            f"({len(matches)} matches)",
            file=sys.stderr,
        )
        sys.exit(2)
    return matches[0]


def _criterion_values(value: str | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def _quote(value: str) -> str:
    if not value or any(char.isspace() or char in '|"' for char in value):
        return json.dumps(value)
    return value


def _match_text(rule: dict[str, Any]) -> str:
    match = rule.get("match") or {}
    parts = [
        f"{key}={'|'.join(_quote(value) for value in _criterion_values(match[key]))}"
        for key in _CRITERIA_ORDER
        if key in match
    ]
    return " AND ".join(parts) if parts else "every notification"


def _sets_sound(rule: dict[str, Any]) -> bool:
    sound = rule.get("sound")
    return isinstance(sound, str) and bool(sound.strip())


def _sound_text(sound: NotificationSound) -> str:
    return sound.path if sound.kind == SOUND_FILE and sound.path else sound.kind


def _toast_text(toast: bool) -> str:
    return "shown" if toast else "hidden"


def _toast_style(toast: bool) -> str:
    return "green" if toast else "red"


def _sound_style(sound: str) -> str:
    """Style a sound word: ``bell`` and ``none`` are reserved, anything else is a file."""
    return {"bell": "green", "none": "red"}.get(sound.lower(), "blue")


def _print_rules(
    out: Console,
    applied: Sequence[ConfiguredNotificationRule],
    ignored: Sequence[ConfiguredNotificationRule],
) -> None:
    defaults = DEFAULT_NOTIFICATION_DELIVERY
    default_text = Text.assemble(
        "Anything no matching rule sets keeps the default: toast ",
        (_toast_text(defaults.toast), _toast_style(defaults.toast)),
        ", sound ",
        (_sound_text(defaults.sound), _sound_style(defaults.sound.kind)),
        ".",
    )
    if not applied:
        out.print(Text("No notification delivery rules are configured.", style="bold"))
        out.print(default_text, soft_wrap=True)
    else:
        out.print(
            Text.assemble(
                ("Notification delivery rules", "bold"),
                (f" ({len(applied)})", "dim"),
            )
        )
        out.print(
            Text(
                "Rules are consulted in this order (highest priority first, then "
                "config order); for toast and for sound separately, the first "
                "matching rule that sets the field decides it.",
                style="dim",
            ),
            soft_wrap=True,
        )
        for position, entry in enumerate(_evaluation_order(applied), start=1):
            _print_rule(out, position, entry)
        out.print()
        out.print(default_text, soft_wrap=True)
    if ignored:
        out.print()
        out.print(
            Text(f"Ignored entries ({len(ignored)})", style="bold yellow"),
        )
        for entry in ignored:
            for problem in entry.problems:
                out.print(
                    Text.assemble(
                        "  ",
                        (f"{entry.layer}", "dim"),
                        f" entry {entry.layer_index}: {problem}",
                    ),
                    soft_wrap=True,
                )
        out.print(
            Text(
                "Run `sase doctor -C config.notification_rules` for details.",
                style="dim",
            )
        )


def _print_rule(out: Console, position: int, entry: ConfiguredNotificationRule) -> None:
    rule = entry.rule or {}
    header = Text.assemble(
        f"{position:>2}. ",
        (entry.label, "bold cyan"),
        ("  [", "dim"),
        (entry.layer, "dim"),
        ("]", "dim"),
    )
    if entry.priority:
        header.append(f"  priority {entry.priority}", style="magenta")
    out.print()
    out.print(header, soft_wrap=True)
    description = rule.get("description")
    if description:
        out.print(Text(f"      {description}", style="italic"), soft_wrap=True)
    out.print(
        Text.assemble(("      match  ", "dim"), _match_text(rule)), soft_wrap=True
    )
    if "toast" in rule:
        out.print(
            Text.assemble(
                ("      toast  ", "dim"),
                (_toast_text(rule["toast"]), _toast_style(rule["toast"])),
            )
        )
    if _sets_sound(rule):
        sound = str(rule["sound"])
        out.print(
            Text.assemble(("      sound  ", "dim"), (sound, _sound_style(sound))),
            soft_wrap=True,
        )


def _print_explanation(
    out: Console,
    notification: Notification,
    tab: str,
    delivery: NotificationDelivery,
    applied: Sequence[ConfiguredNotificationRule],
) -> None:
    layers = _layers_by_label(applied)
    fields = [
        ("tab", tab or "-"),
        ("sender", notification.sender),
        ("action", notification.action or "-"),
        ("tags", ", ".join(notification.tags) or "-"),
        ("title", _title(notification) or "-"),
    ]
    out.print(Text.assemble(("Notification ", "bold"), (notification.id, "bold cyan")))
    for name, value in fields:
        out.print(Text.assemble((f"  {name:<8}", "dim"), value), soft_wrap=True)
    out.print()
    out.print(Text("Delivery", style="bold"))
    rows = [
        (
            "toast",
            _toast_text(delivery.toast),
            _toast_style(delivery.toast),
            delivery.toast_rule,
        ),
        (
            "sound",
            _sound_text(delivery.sound),
            _sound_style(delivery.sound.kind),
            delivery.sound_rule,
        ),
    ]
    for name, value, style, rule_label in rows:
        line = Text.assemble((f"  {name:<8}", "dim"), (value, style))
        line.append("  <- ", style="dim")
        if rule_label is None:
            line.append(f"default (no matching rule sets {name})", style="dim")
        else:
            line.append(rule_label, style="cyan")
            layer_text = ", ".join(layers.get(rule_label, ()))
            if layer_text:
                line.append(f"  [{layer_text}]", style="dim")
        out.print(line, soft_wrap=True)


def _title(notification: Notification) -> str:
    return notification.notes[0] if notification.notes else ""


def _layers_by_label(
    applied: Sequence[ConfiguredNotificationRule],
) -> dict[str, list[str]]:
    layers: dict[str, list[str]] = {}
    for entry in applied:
        if entry.layer not in layers.setdefault(entry.label, []):
            layers[entry.label].append(entry.layer)
    return layers


def _print_json(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _defaults_json() -> dict[str, Any]:
    defaults = DEFAULT_NOTIFICATION_DELIVERY
    return {"toast": defaults.toast, "sound": _sound_text(defaults.sound)}


def _rules_json(
    applied: Sequence[ConfiguredNotificationRule],
    ignored: Sequence[ConfiguredNotificationRule],
) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    for position, entry in enumerate(_evaluation_order(applied), start=1):
        rule = entry.rule or {}
        rules.append(
            {
                "order": position,
                "index": entry.index,
                "label": entry.label,
                "name": rule.get("name"),
                "description": rule.get("description"),
                "layer": entry.layer,
                "priority": entry.priority,
                "match": rule.get("match", {}),
                "toast": rule.get("toast"),
                "sound": rule.get("sound") if _sets_sound(rule) else None,
            }
        )
    return {
        "defaults": _defaults_json(),
        "rules": rules,
        "ignored": [
            {
                "layer": entry.layer,
                "layer_index": entry.layer_index,
                "problems": list(entry.problems),
            }
            for entry in ignored
        ],
    }


def _explain_json(
    notification: Notification,
    tab: str,
    delivery: NotificationDelivery,
    applied: Sequence[ConfiguredNotificationRule],
) -> dict[str, Any]:
    layers = _layers_by_label(applied)

    def decided_by(label: str | None) -> dict[str, Any]:
        return {"rule": label, "layers": layers.get(label, []) if label else []}

    return {
        "notification": {
            "id": notification.id,
            "tab": tab,
            "sender": notification.sender,
            "action": notification.action or "",
            "tags": list(notification.tags),
            "title": _title(notification),
        },
        "delivery": {
            "toast": {"value": delivery.toast, **decided_by(delivery.toast_rule)},
            "sound": {
                "value": _sound_text(delivery.sound),
                "kind": delivery.sound.kind,
                **decided_by(delivery.sound_rule),
            },
        },
    }
