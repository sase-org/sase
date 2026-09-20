"""Config parsing and batched resolution for notification delivery rules."""

from __future__ import annotations

import importlib.resources
from collections.abc import Iterator
from typing import Any

import pytest

from sase.config.loading import load_default_config
from sase.core import notification_store_facade
from sase.core.notification_store_wire import (
    NotificationDeliveryWire,
    NotificationSoundWire,
    notification_deliveries_from_list,
)
from sase.notifications import delivery
from sase.notifications.delivery import (
    DEFAULT_NOTIFICATION_DELIVERY,
    NotificationDelivery,
    NotificationSound,
    notification_delivery_rules,
    resolve_notification_deliveries,
)
from sase.notifications.models import Notification


@pytest.fixture(autouse=True)
def _clean_rule_cache() -> Iterator[None]:
    delivery._delivery_rules_for_token.cache_clear()
    yield
    delivery._delivery_rules_for_token.cache_clear()


def _use_config(
    monkeypatch: pytest.MonkeyPatch,
    ace: dict[str, Any],
    *,
    token: tuple[Any, ...] = ("token",),
) -> None:
    monkeypatch.setattr(delivery, "load_merged_config", lambda: {"ace": ace})
    monkeypatch.setattr(delivery, "current_config_token", lambda: token)


def _use_rules(monkeypatch: pytest.MonkeyPatch, rules: object) -> None:
    _use_config(monkeypatch, {"notification_rules": rules})


def _notification(
    *,
    id: str = "n1",
    sender: str = "user-agent",
    action: str | None = None,
    tags: list[str] | None = None,
    notes: list[str] | None = None,
    panel: str | None = None,
) -> Notification:
    return Notification(
        id=id,
        timestamp="2026-09-20T12:00:00+00:00",
        sender=sender,
        notes=notes if notes is not None else ["Headline"],
        tags=tags or [],
        action=action,
        action_data={"panel": panel} if panel else {},
    )


def _task_triage(id: str = "bead-1") -> Notification:
    return _notification(
        id=id,
        sender="bead",
        action="TaskTriage",
        tags=["bead", "task"],
        panel="beads",
    )


def _axe_error(id: str = "axe-1") -> Notification:
    return _notification(id=id, sender="axe", action="ViewErrorReport")


# --- config parsing ----------------------------------------------------------


def test_no_configured_rules_reads_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_config(monkeypatch, {})

    assert notification_delivery_rules() == ()


def test_shipped_default_config_has_no_rules() -> None:
    defaults = load_default_config(importlib.resources.files)

    assert defaults["ace"]["notification_rules"] == []


def test_rule_passes_through_in_wire_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_rules(
        monkeypatch,
        [
            {
                "name": "quiet-task-beads",
                "description": "Too noisy right now.",
                "priority": 5,
                "match": {"tab": "beads", "tags": ["bead", "task"]},
                "toast": False,
                "sound": "none",
            }
        ],
    )

    assert notification_delivery_rules() == (
        {
            "name": "quiet-task-beads",
            "description": "Too noisy right now.",
            "priority": 5,
            "match": {"tab": "beads", "tags": ["bead", "task"]},
            "toast": False,
            "sound": "none",
        },
    )


def test_bare_string_criterion_is_kept_as_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_rules(monkeypatch, [{"match": {"sender": "axe"}, "sound": "bell"}])

    assert notification_delivery_rules() == (
        {"match": {"sender": "axe"}, "sound": "bell"},
    )


def test_missing_match_stays_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_rules(monkeypatch, [{"name": "mac-chime", "sound": "/tmp/glass.aiff"}])

    assert notification_delivery_rules() == (
        {"name": "mac-chime", "sound": "/tmp/glass.aiff"},
    )


def test_empty_criterion_list_is_kept_so_the_core_matches_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_rules(monkeypatch, [{"match": {"tags": []}, "toast": False}])

    assert notification_delivery_rules() == ({"match": {"tags": []}, "toast": False},)


def test_null_valued_optional_fields_read_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_rules(
        monkeypatch,
        [{"name": None, "priority": None, "toast": None, "sound": "none"}],
    )

    assert notification_delivery_rules() == ({"sound": "none"},)


@pytest.mark.parametrize(
    "junk",
    [
        pytest.param("not a rule", id="non-dict-entry"),
        pytest.param({"sound": "none", "volume": 3}, id="unknown-rule-key"),
        pytest.param({"match": {"tabs": "beads"}}, id="unknown-match-key"),
        pytest.param({"match": "beads"}, id="match-not-an-object"),
        pytest.param({"match": None, "toast": False}, id="null-match"),
        pytest.param({"match": {"tab": None}, "toast": False}, id="blank-criterion"),
        pytest.param({"match": {"tab": 7}}, id="numeric-criterion"),
        pytest.param({"match": {"tags": ["ok", 7]}}, id="non-string-list-item"),
        pytest.param({"toast": "no"}, id="string-toast"),
        pytest.param({"toast": 0}, id="int-toast"),
        pytest.param({"sound": 3}, id="non-string-sound"),
        pytest.param({"name": 3}, id="non-string-name"),
        pytest.param({"description": ["x"]}, id="non-string-description"),
        pytest.param({"priority": "high"}, id="string-priority"),
        pytest.param({"priority": True}, id="bool-priority"),
        pytest.param({"priority": 1001}, id="priority-above-schema-bound"),
        pytest.param({"priority": -1001}, id="priority-below-schema-bound"),
        pytest.param({1: "numeric key"}, id="non-string-key"),
    ],
)
def test_malformed_rule_is_skipped_and_neighbors_survive(
    monkeypatch: pytest.MonkeyPatch, junk: object
) -> None:
    _use_rules(
        monkeypatch, [{"name": "first", "sound": "bell"}, junk, {"name": "last"}]
    )

    assert notification_delivery_rules() == (
        {"name": "first", "sound": "bell"},
        {"name": "last"},
    )


@pytest.mark.parametrize("junk", ["beads", {"name": "x"}, 4, None])
def test_non_list_rules_block_reads_as_empty(
    monkeypatch: pytest.MonkeyPatch, junk: object
) -> None:
    _use_rules(monkeypatch, junk)

    assert notification_delivery_rules() == ()


def test_unreadable_config_reads_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> dict[str, Any]:
        raise OSError("config unreadable")

    monkeypatch.setattr(delivery, "load_merged_config", boom)
    monkeypatch.setattr(delivery, "current_config_token", lambda: ("token",))

    assert notification_delivery_rules() == ()


def test_non_mapping_ace_block_reads_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(delivery, "load_merged_config", lambda: {"ace": "oops"})
    monkeypatch.setattr(delivery, "current_config_token", lambda: ("token",))

    assert notification_delivery_rules() == ()


# --- token cache -------------------------------------------------------------


def test_rules_are_read_once_per_config_token(monkeypatch: pytest.MonkeyPatch) -> None:
    reads: list[int] = []

    def load() -> dict[str, Any]:
        reads.append(1)
        return {"ace": {"notification_rules": [{"sound": "none"}]}}

    monkeypatch.setattr(delivery, "load_merged_config", load)
    monkeypatch.setattr(delivery, "current_config_token", lambda: ("same",))

    first = notification_delivery_rules()
    second = notification_delivery_rules()

    assert first == second == ({"sound": "none"},)
    assert len(reads) == 1


def test_a_new_config_token_rereads_the_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_rules(monkeypatch, [{"sound": "none"}])
    assert notification_delivery_rules() == ({"sound": "none"},)

    _use_config(
        monkeypatch,
        {"notification_rules": [{"sound": "/tmp/a.wav"}]},
        token=("edited",),
    )

    assert notification_delivery_rules() == ({"sound": "/tmp/a.wav"},)


# --- resolution --------------------------------------------------------------


def test_empty_batch_resolves_without_reading_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> dict[str, Any]:
        raise AssertionError("config must not be read for an empty batch")

    monkeypatch.setattr(delivery, "load_merged_config", boom)

    assert resolve_notification_deliveries([]) == []


def test_no_rules_resolves_to_defaults_without_a_core_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {})

    def boom(*args: object) -> object:
        raise AssertionError(f"the core must not be consulted with no rules: {args}")

    monkeypatch.setattr(delivery, "resolve_wire_deliveries", boom)

    assert resolve_notification_deliveries([_task_triage(), _axe_error()]) == [
        DEFAULT_NOTIFICATION_DELIVERY,
        DEFAULT_NOTIFICATION_DELIVERY,
    ]


def test_python_default_matches_the_core_default_for_an_empty_rule_list() -> None:
    rows = [
        _notification(),
        _task_triage(),
        _axe_error(),
        _notification(sender="gate", action="GateExecutionFailed", tags=["gate"]),
        _notification(notes=[]),
    ]

    wires = notification_store_facade.resolve_notification_deliveries([], rows)

    assert len(wires) == len(rows)
    for wire in wires:
        assert delivery._delivery_from_wire(wire) == DEFAULT_NOTIFICATION_DELIVERY
    assert DEFAULT_NOTIFICATION_DELIVERY == NotificationDelivery(
        toast=True, sound=NotificationSound(kind="bell")
    )


def test_configured_rules_resolve_through_the_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_rules(
        monkeypatch,
        [
            {
                "name": "quiet-task-beads",
                "match": {"tab": "beads"},
                "toast": False,
                "sound": "none",
            },
            {"name": "mbp-chime", "sound": "/System/Library/Sounds/Glass.aiff"},
        ],
    )

    deliveries = resolve_notification_deliveries([_task_triage(), _axe_error()])

    assert deliveries == [
        NotificationDelivery(
            toast=False,
            sound=NotificationSound(kind="none"),
            toast_rule="quiet-task-beads",
            sound_rule="quiet-task-beads",
        ),
        NotificationDelivery(
            toast=True,
            sound=NotificationSound(
                kind="file", path="/System/Library/Sounds/Glass.aiff"
            ),
            toast_rule=None,
            sound_rule="mbp-chime",
        ),
    ]


def test_unnamed_rule_label_counts_the_surviving_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_rules(monkeypatch, [{"match": {"tabs": "beads"}}, {"toast": False}])

    [resolved] = resolve_notification_deliveries([_axe_error()])

    assert resolved.toast is False
    assert resolved.toast_rule == "rule[0]"


def test_resolution_preserves_input_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_rules(monkeypatch, [{"match": {"sender": "axe"}, "toast": False}])
    rows = [_axe_error("a"), _task_triage("b"), _axe_error("c")]

    deliveries = resolve_notification_deliveries(rows)

    assert [d.toast for d in deliveries] == [False, True, False]


# --- wire conversion ---------------------------------------------------------


def test_deliveries_rehydrate_every_sound_kind() -> None:
    payload = [
        {"schema_version": 1, "toast": True, "sound": {"kind": "bell"}},
        {
            "schema_version": 1,
            "toast": False,
            "sound": {"kind": "none"},
            "toast_rule": "quiet",
            "sound_rule": "quiet",
        },
        {
            "schema_version": 1,
            "toast": True,
            "sound": {"kind": "file", "path": "/tmp/a.wav"},
            "sound_rule": "rule[2]",
        },
    ]

    assert notification_deliveries_from_list(payload) == [
        NotificationDeliveryWire(1, True, NotificationSoundWire("bell")),
        NotificationDeliveryWire(
            1, False, NotificationSoundWire("none"), "quiet", "quiet"
        ),
        NotificationDeliveryWire(
            1,
            True,
            NotificationSoundWire("file", "/tmp/a.wav"),
            None,
            "rule[2]",
        ),
    ]


def test_delivery_schema_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="schema mismatch"):
        notification_deliveries_from_list(
            [{"schema_version": 99, "toast": True, "sound": {"kind": "bell"}}]
        )


def test_unknown_sound_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown notification sound kind"):
        notification_deliveries_from_list(
            [{"schema_version": 1, "toast": True, "sound": {"kind": "speech"}}]
        )


def test_facade_rejects_a_delivery_count_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_binding(*args: object) -> list[dict[str, Any]]:
        del args
        return []

    monkeypatch.setattr(
        notification_store_facade, "require_rust_binding", lambda _: fake_binding
    )

    with pytest.raises(ValueError, match="resolved 0 notification deliveries"):
        notification_store_facade.resolve_notification_deliveries([], [_axe_error()])
