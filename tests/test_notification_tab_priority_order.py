"""Tab-strip order is the core's list, stably re-sorted by effective priority."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from sase.ace.tui.modals.notification_modal_tags import (
    MUTED_TAB_KEY,
    SNOOZED_TAB_KEY,
    notification_tabs_from_core,
)
from sase.ace.tui.widgets import notification_tab_style
from sase.ace.tui.widgets.notification_tab_style import (
    default_notification_tab_priority,
)
from sase.core.notification_store_facade import classify_notification_tabs
from sase.notifications.models import Notification

from tests.notification_store.helpers import make_notification


@pytest.fixture(autouse=True)
def _no_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Start every test from an empty ``ace`` block, cached per test."""
    _use_config(monkeypatch, {})
    yield
    notification_tab_style._configured_tab_styles_for_token.cache_clear()
    notification_tab_style._indicator_max_counts_for_token.cache_clear()


def _use_config(monkeypatch: pytest.MonkeyPatch, ace: dict[str, Any]) -> None:
    """Point the resolver at *ace* with a token that busts its own cache."""
    notification_tab_style._configured_tab_styles_for_token.cache_clear()
    notification_tab_style._indicator_max_counts_for_token.cache_clear()
    monkeypatch.setattr(
        notification_tab_style,
        "load_merged_config",
        lambda: {"ace": ace},
    )


def _snoozed(notification: Notification, until: str) -> Notification:
    notification.muted = True
    notification.snooze_until = until
    return notification


def _every_kind_rows() -> list[Notification]:
    """One row for every tab kind the core's ``ordered_tab_keys`` produces."""
    error = make_notification(id="error", action="ViewErrorReport")
    error.sender = "axe"
    muted = make_notification(id="muted")
    muted.muted = True
    return [
        make_notification(id="hitl", action="PlanApproval"),
        make_notification(
            id="beads", action="TaskTriage", action_data={"panel": "beads"}
        ),
        make_notification(
            id="deploy", action="CustomGate", action_data={"panel": "deployments"}
        ),
        error,
        make_notification(id="general"),
        make_notification(id="done", tags=["done"]),
        make_notification(id="alpha", tags=["alpha"]),
        make_notification(id="zeta", tags=["zeta"]),
        _snoozed(make_notification(id="snoozed"), "2099-01-01T09:00:00-05:00"),
        muted,
    ]


def test_without_overrides_the_adapter_preserves_the_core_order() -> None:
    """A stable sort of an already-correct list is the identity.

    This is the parity pin: the Python ladder must stay non-increasing along
    the real core's order, and with no config the adapter must not reshuffle.
    """
    classification = classify_notification_tabs(_every_kind_rows())
    core_keys = [tab.key for tab in classification.tabs]
    adapted = notification_tabs_from_core(classification.tabs)
    adapted_keys = ["general" if tab.tag is None else tab.tag for tab in adapted]

    assert adapted_keys == core_keys
    defaults = [default_notification_tab_priority(tab) for tab in adapted]
    assert defaults == sorted(defaults, reverse=True)
    assert core_keys == [
        "hitl",
        "beads",
        "deployments",
        "errors",
        "general",
        "done",
        "alpha",
        "zeta",
        SNOOZED_TAB_KEY,
        MUTED_TAB_KEY,
    ]


def test_shipped_beads_priority_sorts_after_custom_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {"notification_tabs": {"beads": {"priority": 0}}})
    classification = classify_notification_tabs(_every_kind_rows())
    adapted_keys = [
        "general" if tab.tag is None else tab.tag
        for tab in notification_tabs_from_core(classification.tabs)
    ]

    assert adapted_keys == [
        "hitl",
        "deployments",
        "errors",
        "general",
        "done",
        "alpha",
        "zeta",
        "beads",
        SNOOZED_TAB_KEY,
        MUTED_TAB_KEY,
    ]


def test_a_tag_configured_above_gates_sorts_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {"notification_tabs": {"review": {"priority": 70}}})
    rows = [
        make_notification(id="hitl", action="PlanApproval"),
        make_notification(id="review", tags=["review"]),
    ]
    classification = classify_notification_tabs(rows)
    adapted_keys = [tab.tag for tab in notification_tabs_from_core(classification.tabs)]

    assert adapted_keys == ["review", "hitl"]


def test_equal_priority_panels_keep_the_core_label_order() -> None:
    """The adapter's sort is stable, so the core's label order is the tiebreak."""
    rows = [
        make_notification(
            id="zeta", action="CustomGate", action_data={"panel": "zeta-panel"}
        ),
        make_notification(
            id="alpha", action="CustomGate", action_data={"panel": "alpha-panel"}
        ),
    ]
    classification = classify_notification_tabs(rows)
    core_keys = [tab.key for tab in classification.tabs]
    adapted_keys = [tab.tag for tab in notification_tabs_from_core(classification.tabs)]

    assert core_keys == ["alpha-panel", "zeta-panel"]
    assert adapted_keys == core_keys
