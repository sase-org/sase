"""Shared queue-weight validation and successor inheritance."""

from __future__ import annotations

from sase.core.runner_slots import inheritable_queue_weight, valid_queue_weight


def test_valid_queue_weight_accepts_explicit_zero() -> None:
    assert valid_queue_weight(0, explicit=True) == 0.0
    assert valid_queue_weight(0.0, explicit=True) == 0.0


def test_valid_queue_weight_rejects_implicit_zero() -> None:
    assert valid_queue_weight(0.0, explicit=False) is None


def test_valid_queue_weight_rejects_non_finite_and_negative() -> None:
    assert valid_queue_weight(-1, explicit=True) is None
    assert valid_queue_weight(True, explicit=True) is None
    assert valid_queue_weight(float("inf"), explicit=True) is None
    assert valid_queue_weight(float("nan"), explicit=True) is None
    assert valid_queue_weight("0", explicit=True) is None


def test_valid_queue_weight_accepts_positive() -> None:
    assert valid_queue_weight(0.25, explicit=False) == 0.25
    assert valid_queue_weight(2, explicit=True) == 2.0


def test_inheritable_queue_weight_keeps_user_authored_zero_explicit() -> None:
    assert inheritable_queue_weight(
        {"queue_weight": 0.0, "queue_weight_explicit": True}
    ) == (0.0, True)


def test_inheritable_queue_weight_inherits_positive_implicitly() -> None:
    assert inheritable_queue_weight(
        {"queue_weight": 2.0, "queue_weight_explicit": True}
    ) == (2.0, False)


def test_inheritable_queue_weight_skips_host_override_zero() -> None:
    assert inheritable_queue_weight(
        {
            "queue_weight": 0.0,
            "queue_weight_explicit": True,
            "monitor_queue_weight_overridden": True,
            "monitor_inherited_queue_weight": 3.0,
            "monitor_inherited_queue_weight_explicit": True,
        }
    ) == (3.0, False)


def test_inheritable_queue_weight_host_override_without_starter_weight() -> None:
    assert inheritable_queue_weight(
        {
            "queue_weight": 0.0,
            "queue_weight_explicit": True,
            "monitor_queue_weight_overridden": True,
        }
    ) == (None, False)


def test_inheritable_queue_weight_rejects_implicit_zero() -> None:
    assert inheritable_queue_weight({"queue_weight": 0.0}) == (None, False)
    assert inheritable_queue_weight({}) == (None, False)
