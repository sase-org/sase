"""Layer provenance and drop reasons for ``ace.notification_rules``."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from sase.config.layers import ConfigLayer
from sase.core.notification_store_facade import (
    resolve_notification_deliveries as resolve_wire_deliveries,
)
from sase.notifications import delivery
from sase.notifications.delivery import (
    configured_notification_rules,
    notification_delivery_rules,
    notification_rule_label,
)
from sase.notifications.models import Notification


def _layer(
    name: str,
    ace: object = None,
    *,
    strategy: str = "concatenate",
    rules: object = None,
) -> ConfigLayer:
    data: dict[str, Any] = {}
    if ace is not None:
        data["ace"] = ace
    elif rules is not None:
        data["ace"] = {"notification_rules": rules}
    return ConfigLayer(
        name=name, path=None, exists=True, list_strategy=strategy, data=data
    )


@pytest.fixture(autouse=True)
def _clean_rule_cache() -> Iterator[None]:
    delivery._delivery_rules_for_token.cache_clear()
    yield
    delivery._delivery_rules_for_token.cache_clear()


def _use_layers(monkeypatch: pytest.MonkeyPatch, *layers: ConfigLayer) -> None:
    monkeypatch.setattr(delivery, "load_config_layers", lambda: list(layers))


def _layer_names(monkeypatch: pytest.MonkeyPatch, *layers: ConfigLayer) -> list[str]:
    _use_layers(monkeypatch, *layers)
    return [entry.label for entry in configured_notification_rules()]


def test_user_rules_precede_overlay_rules_and_keep_their_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_layers(
        monkeypatch,
        _layer("default", rules=[]),
        _layer(
            "user",
            strategy="replace",
            rules=[{"name": "quiet", "toast": False}],
        ),
        _layer("overlay:sase_mac.yml", rules=[{"name": "chime", "sound": "a.wav"}]),
    )

    configured = configured_notification_rules()

    assert [(entry.layer, entry.label) for entry in configured] == [
        ("user", "quiet"),
        ("overlay:sase_mac.yml", "chime"),
    ]
    assert [entry.index for entry in configured] == [0, 1]
    assert [entry.layer_index for entry in configured] == [0, 0]


def test_replace_layer_discards_earlier_layers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels = _layer_names(
        monkeypatch,
        _layer("plugin:x", rules=[{"name": "from-plugin", "toast": False}]),
        _layer("user", strategy="replace", rules=[{"name": "mine", "toast": False}]),
        _layer("local", rules=[{"name": "project", "toast": False}]),
    )

    assert labels == ["mine", "project"]


def test_non_list_value_overrides_the_merged_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels = _layer_names(
        monkeypatch,
        _layer("user", strategy="replace", rules=[{"name": "a", "toast": False}]),
        _layer("overlay:sase_x.yml", rules="oops"),
        _layer("local", rules=[{"name": "b", "toast": False}]),
    )

    assert labels == ["b"]


def test_non_mapping_ace_section_overrides_the_merged_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels = _layer_names(
        monkeypatch,
        _layer("user", strategy="replace", rules=[{"name": "a", "toast": False}]),
        _layer("overlay:sase_x.yml", ace="oops"),
    )

    assert labels == []


def test_layers_without_the_key_change_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels = _layer_names(
        monkeypatch,
        _layer("user", strategy="replace", rules=[{"name": "a", "toast": False}]),
        _layer("overlay:sase_x.yml", ace={"page_size": 5}),
        _layer("local"),
    )

    assert labels == ["a"]


def test_dropped_entries_carry_reasons_and_do_not_consume_an_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_layers(
        monkeypatch,
        _layer(
            "user",
            strategy="replace",
            rules=[
                {"name": "bad", "bogus": 1, "match": {"nope": "x"}, "toast": "yes"},
                {"toast": False},
                "not a rule",
            ],
        ),
    )

    bad, kept, junk = configured_notification_rules()

    assert bad.rule is None and bad.index is None
    assert bad.label == "bad"
    assert bad.problems == (
        "unknown rule key 'bogus' (expected one of description, match, name, "
        "priority, sound, toast)",
        "toast must be true or false",
        "unknown match criterion 'nope' (expected one of action, note, sender, "
        "tab, tags, title)",
    )
    assert (kept.index, kept.label) == (0, "rule[0]")
    assert junk.problems == ("a rule must be a mapping, not str",)


@pytest.mark.parametrize(
    ("raw", "problem"),
    [
        ({"match": None}, "match must be a mapping, not NoneType"),
        ({"match": {"tab": None}}, "match.tab must be a string or a list of strings"),
        ({"match": {"tags": ["a", 1]}}, "match.tags must be a string or a list"),
        ({"name": 5}, "name must be a string"),
        ({"priority": True}, "priority must be an integer from -1000 to 1000"),
        ({"priority": 1001}, "priority must be an integer from -1000 to 1000"),
    ],
)
def test_each_malformed_shape_reports_its_reason(
    monkeypatch: pytest.MonkeyPatch, raw: dict[str, Any], problem: str
) -> None:
    _use_layers(monkeypatch, _layer("user", strategy="replace", rules=[raw]))

    (entry,) = configured_notification_rules()

    assert entry.rule is None
    assert problem in " | ".join(entry.problems)


def test_priority_property_defaults_to_zero_and_ignored_rules_have_none() -> None:
    kept = delivery.ConfiguredNotificationRule(
        layer="user",
        layer_index=0,
        raw={},
        rule={"priority": 7, "toast": False},
        index=0,
        label="rule[0]",
    )
    plain = delivery.ConfiguredNotificationRule(
        layer="user",
        layer_index=1,
        raw={},
        rule={"toast": False},
        index=1,
        label="rule[1]",
    )
    dropped = delivery.ConfiguredNotificationRule(
        layer="user",
        layer_index=2,
        raw="junk",
        rule=None,
        index=None,
        label="(ignored)",
    )

    assert (kept.priority, plain.priority, dropped.priority) == (7, 0, 0)


def test_labels_match_the_names_the_core_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The listing must name rules exactly as ``--explain`` will."""
    _use_layers(
        monkeypatch,
        _layer(
            "user",
            strategy="replace",
            rules=[
                {"bogus": True},
                {"match": {"sender": "nobody"}, "toast": False},
                {"name": "", "match": {"sender": "wanted"}, "sound": "none"},
                {"name": "named", "match": {"sender": "wanted"}, "toast": False},
            ],
        ),
    )
    monkeypatch.setattr(
        delivery,
        "load_merged_config",
        lambda: {
            "ace": {
                "notification_rules": [
                    {"match": {"sender": "nobody"}, "toast": False},
                    {"name": "", "match": {"sender": "wanted"}, "sound": "none"},
                    {"name": "named", "match": {"sender": "wanted"}, "toast": False},
                ]
            }
        },
    )
    monkeypatch.setattr(delivery, "current_config_token", lambda: ("t",))
    row = Notification(
        id="n1", timestamp="2026-09-20T12:00:00+00:00", sender="wanted", notes=["x"]
    )

    configured = configured_notification_rules()
    (resolved,) = resolve_wire_deliveries(list(notification_delivery_rules()), [row])

    assert [entry.rule for entry in configured if entry.rule] == list(
        notification_delivery_rules()
    )
    labels = {entry.label for entry in configured}
    assert resolved.toast_rule in labels
    assert resolved.sound_rule in labels
    assert (resolved.toast_rule, resolved.sound_rule) == ("named", "rule[1]")


def test_notification_rule_label_falls_back_to_position() -> None:
    assert notification_rule_label({"name": "quiet"}, 4) == "quiet"
    assert notification_rule_label({"name": ""}, 4) == "rule[4]"
    assert notification_rule_label({}, 0) == "rule[0]"
