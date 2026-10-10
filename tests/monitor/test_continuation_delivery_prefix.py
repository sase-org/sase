"""Queue/auto prefix and wire-extra unit tests."""

from __future__ import annotations

from sase.monitor.continuation_delivery import (
    launch_wire_extra,
    queue_launch_prefix,
)

from ._continuation_delivery import continuation_delivery_sandbox  # noqa: F401

__all__ = [
    "test_epic_launch_monitor_override_is_not_inherited_by_successors",
    "test_epic_launch_monitor_override_without_starter_weight_is_not_inherited",
    "test_launch_wire_extra_keeps_user_authored_zero",
    "test_launch_wire_extra_preserves_canonical_capacity",
    "test_queue_launch_prefix_keeps_user_authored_zero",
    "test_queue_launch_prefix_legacy_zero_does_not_reenter_on_parser",
    "test_queue_launch_prefix_omits_implicit_zero",
    "test_queue_launch_prefix_omits_legacy_zero",
    "test_queue_launch_prefix_positive_budget_is_parseable",
    "test_queue_launch_prefix_prefers_canonical_capacity",
    "test_queue_launch_prefix_reauthors_capacity_multiplier",
]


def test_queue_launch_prefix_prefers_canonical_capacity() -> None:
    prefix = queue_launch_prefix(
        {
            "wait_priority": 0,
            "wait_runners": 0,
            "wait_runners_explicit": True,
            "queue_priority": 7,
            "queue_capacity": 3,
            "queue_capacity_explicit": True,
            "queue_weight": 0.25,
        }
    )

    assert prefix == "%queue(capacity=3, priority=0, weight=0.25)\n"


def test_queue_launch_prefix_omits_legacy_zero() -> None:
    prefix = queue_launch_prefix(
        {
            "wait_runners": 0,
            "wait_runners_explicit": True,
            "wait_priority": 0,
            "queue_weight": 0.25,
        }
    )

    assert prefix == "%queue(priority=0, weight=0.25)\n"


def test_queue_launch_prefix_omits_implicit_zero() -> None:
    prefix = queue_launch_prefix(
        {
            "wait_runners": 0,
            "wait_runners_explicit": False,
            "queue_weight": 2.0,
        }
    )

    assert prefix == "%queue(weight=2)\n"


def test_queue_launch_prefix_reauthors_capacity_multiplier() -> None:
    meta = {
        "queue_capacity_multiplier": 1.5,
        "wait_priority": 0,
        "queue_weight": 0.25,
    }
    prefix = queue_launch_prefix(meta)

    assert prefix == "%queue(capacity=1.5x, priority=0, weight=0.25)\n"
    assert launch_wire_extra(meta) == {
        "queue_capacity_multiplier": 1.5,
        "queue_weight": 0.25,
        "queue_weight_explicit": False,
    }


def test_followup_prompt_carries_no_auto_prefix() -> None:
    """Follow-up prompts re-emit no ``%auto``: successors inherit structurally.

    Autonomy rides the successor's inherited record (``source: inherited``),
    never a re-emitted prompt prefix. The record selection renders the exact
    token only for prompt-rewrite paths (retry, runner refresh, ``A``).
    """
    from sase.autonomy.record import read_record, selection_to_prompt_prefix

    record = read_record(
        {
            "autonomy": {
                "profile": "tale",
                "selection": "tale",
            }
        }
    )
    assert record is not None
    # The rewrite token still derives exactly from the selection (``:plan``
    # preserved), but follow-up composition emits only the queue prefix.
    assert selection_to_prompt_prefix(record.get("selection")) == "%auto:tale\n"
    assert selection_to_prompt_prefix("plan") == "%auto:plan\n"
    assert selection_to_prompt_prefix("") == "%auto\n"
    assert selection_to_prompt_prefix("manual") == ""


def test_queue_launch_prefix_positive_budget_is_parseable() -> None:
    from sase.macro.directives import extract_prompt_directives

    prefix = queue_launch_prefix(
        {
            "queue_capacity": 100,
            "queue_capacity_explicit": True,
            "wait_priority": 0,
            "queue_weight": 0.25,
        }
    )
    _cleaned, directives = extract_prompt_directives(f"{prefix}continue")

    assert prefix == "%queue(capacity=100, priority=0, weight=0.25)\n"
    assert directives.queue_capacity == 100
    assert directives.wait_runners == 100
    assert directives.wait_priority == 0
    assert directives.queue_weight == 0.25


def test_queue_launch_prefix_legacy_zero_does_not_reenter_on_parser() -> None:
    from sase.macro.directives import extract_prompt_directives

    prefix = queue_launch_prefix(
        {
            "wait_runners": 0,
            "wait_runners_explicit": True,
            "queue_weight": 0.25,
        }
    )
    _cleaned, directives = extract_prompt_directives(f"{prefix}continue")

    assert "capacity=0" not in prefix
    assert directives.queue_capacity is None
    assert directives.queue_weight == 0.25


def test_launch_wire_extra_preserves_canonical_capacity() -> None:
    extra = launch_wire_extra(
        {
            "wait_runners": 0,
            "wait_runners_explicit": True,
            "queue_capacity": 100,
            "queue_capacity_explicit": True,
            "queue_weight": 0.25,
            "queue_weight_explicit": True,
        }
    )

    assert extra["queue_capacity"] == 100
    assert extra["queue_capacity_explicit"] is True
    assert extra["queue_weight"] == 0.25
    assert extra["queue_weight_explicit"] is False


def test_queue_launch_prefix_keeps_user_authored_zero() -> None:
    prefix = queue_launch_prefix(
        {
            "queue_weight": 0.0,
            "queue_weight_explicit": True,
            "wait_priority": 0,
        }
    )

    # The zero-weight core formatter emits an authored zero instead of
    # dropping it, so successors inherit it explicitly.
    assert prefix == "%queue(priority=0, weight=0)\n"


def test_launch_wire_extra_keeps_user_authored_zero() -> None:
    extra = launch_wire_extra(
        {
            "queue_weight": 0.0,
            "queue_weight_explicit": True,
        }
    )

    assert extra["queue_weight"] == 0.0
    assert extra["queue_weight_explicit"] is True


def test_epic_launch_monitor_override_is_not_inherited_by_successors() -> None:
    meta = {
        "queue_weight": 0.0,
        "queue_weight_explicit": True,
        "monitor_queue_weight_overridden": True,
        "monitor_inherited_queue_weight": 3.0,
        "monitor_inherited_queue_weight_explicit": True,
        "wait_priority": 0,
    }

    extra = launch_wire_extra(meta)
    prefix = queue_launch_prefix(meta)

    assert extra["queue_weight"] == 3.0
    assert extra["queue_weight_explicit"] is False
    assert "weight=0" not in prefix
    assert "weight=3" in prefix


def test_epic_launch_monitor_override_without_starter_weight_is_not_inherited() -> None:
    meta = {
        "queue_weight": 0.0,
        "queue_weight_explicit": True,
        "monitor_queue_weight_overridden": True,
    }

    extra = launch_wire_extra(meta)
    prefix = queue_launch_prefix(meta)

    assert "queue_weight" not in extra
    assert "weight=" not in prefix
