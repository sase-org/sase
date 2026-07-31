"""Pure unit coverage for the Admin Center two-slot alternate history."""

from __future__ import annotations

import pytest

from sase.ace.tui.modals.config_center_history import (
    AdminCenterTabHistory,
    validated_admin_center_tab_history,
)


def test_remember_on_empty_history_seeds_current_with_no_alternate() -> None:
    history = AdminCenterTabHistory()

    result = history.remember("logs")

    assert result == AdminCenterTabHistory(current="logs", alternate=None)


def test_remember_with_a_different_tab_shifts_current_into_alternate() -> None:
    history = AdminCenterTabHistory(current="logs", alternate=None)

    result = history.remember("config")

    assert result == AdminCenterTabHistory(current="config", alternate="logs")


def test_remember_with_the_same_tab_returns_the_identical_object() -> None:
    history = AdminCenterTabHistory(current="logs", alternate="config")

    result = history.remember("logs")

    assert result is history


def test_three_way_sequence_keeps_only_the_two_most_recent_sections() -> None:
    history = AdminCenterTabHistory()
    history = history.remember("config")
    history = history.remember("logs")
    history = history.remember("tasks")

    assert history == AdminCenterTabHistory(current="tasks", alternate="logs")


def test_toggle_sequence_ping_pongs_between_exactly_two_sections() -> None:
    history = AdminCenterTabHistory()
    history = history.remember("config")
    history = history.remember("logs")

    history = history.remember("config")
    assert history == AdminCenterTabHistory(current="config", alternate="logs")

    history = history.remember("logs")
    assert history == AdminCenterTabHistory(current="logs", alternate="config")


@pytest.mark.parametrize(
    "sequence",
    [
        ("config",),
        ("config", "logs"),
        ("config", "logs", "tasks"),
        ("config", "logs", "config", "logs", "config"),
        ("config", "config", "logs", "logs", "tasks"),
    ],
)
def test_alternate_never_equals_current_for_any_reachable_sequence(
    sequence: tuple[str, ...],
) -> None:
    history = AdminCenterTabHistory()
    for tab in sequence:
        history = history.remember(tab)  # type: ignore[arg-type]
        assert history.alternate != history.current


def test_validated_history_drops_an_alternate_equal_to_current() -> None:
    assert validated_admin_center_tab_history("logs", "logs") == AdminCenterTabHistory(
        current="logs"
    )


def test_validated_history_keeps_a_distinct_alternate() -> None:
    assert validated_admin_center_tab_history(
        "logs", "config"
    ) == AdminCenterTabHistory(current="logs", alternate="config")
