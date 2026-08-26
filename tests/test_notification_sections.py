"""Pure notification section strategy coverage."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from sase.ace.tui.modals.notification_sections import (
    NOTIFICATION_SECTION_STRATEGIES,
    group_notifications,
    resolve_tab_section_strategy,
)
from sase.ace.tui.widgets import notification_tab_style
from sase.notification_gates.presentation import (
    GATE_CHIP_COLOR_ACTION_DATA_KEY,
    GATE_CHIP_GLYPH_ACTION_DATA_KEY,
    GATE_CHIP_LABEL_ACTION_DATA_KEY,
)
from sase.notifications import Notification

from tests._notification_modal_helpers import _make_notification


@pytest.fixture(autouse=True)
def _clean_tab_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _use_config(monkeypatch, {})
    yield
    notification_tab_style._configured_tab_styles_for_token.cache_clear()
    notification_tab_style._indicator_max_counts_for_token.cache_clear()


def _use_config(monkeypatch: pytest.MonkeyPatch, ace: dict[str, Any]) -> None:
    notification_tab_style._configured_tab_styles_for_token.cache_clear()
    notification_tab_style._indicator_max_counts_for_token.cache_clear()
    monkeypatch.setattr(
        notification_tab_style,
        "load_merged_config",
        lambda: {"ace": ace},
    )


def _bead(
    notification_id: str,
    *,
    action: str = "TaskTriage",
    chip_slug: str | None = None,
    chip_glyph: str = "≈",
    chip_color: str = "#00D7D7",
    request_kind: str | None = None,
    action_data: object | None = None,
) -> Notification:
    if action_data is not None:
        notification = _make_notification(notification_id, action=action)
        notification.action_data = action_data  # type: ignore[assignment]
        return notification

    data = {"panel": "beads"}
    if chip_slug is not None:
        data.update(
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: chip_glyph,
                GATE_CHIP_LABEL_ACTION_DATA_KEY: chip_slug,
                GATE_CHIP_COLOR_ACTION_DATA_KEY: chip_color,
            }
        )
    if request_kind is not None:
        data["request_kind"] = request_kind
    return _make_notification(notification_id, action=action, action_data=data)


def _section_for(notification: Notification):
    strategy = NOTIFICATION_SECTION_STRATEGIES["bead_type"]
    return strategy.section_for(notification)


def test_bead_type_sections_cover_typed_and_untyped_gate_rows() -> None:
    typed = _section_for(_bead("typed", chip_slug="flake"))
    flag = _section_for(
        _bead(
            "flag",
            action="FlagTriage",
            chip_slug="flag",
            chip_glyph="⚑",
            chip_color="#FFAF5F",
        )
    )
    due = _section_for(_bead("due", action="BeadSnooze", request_kind="bead_snooze"))
    cleanup = _section_for(
        _bead(
            "cleanup",
            action="BeadStaleCleanup",
            request_kind="bead_stale_cleanup",
        )
    )
    other = _section_for(_bead("other"))

    assert (typed.label, typed.glyph, typed.color) == (
        "Flaky test",
        "≈",
        "#00D7D7",
    )
    assert (flag.label, flag.glyph) == ("Feature flag", "⚑")
    assert (due.label, due.glyph, due.color) == ("Due", "⏰", "#FFAF00")
    assert (cleanup.label, cleanup.glyph, cleanup.color) == (
        "Cleanup",
        "🧹",
        "#5FAFAF",
    )
    assert (other.label, other.glyph, other.color) == ("Other", "◈", "#AF87FF")


def test_unknown_chip_slug_keeps_chip_presentation_without_degraded_unknown() -> None:
    section = _section_for(
        _bead(
            "unknown",
            chip_slug="bespoke",
            chip_glyph="!",
            chip_color="#010203",
        )
    )

    assert (section.label, section.glyph, section.color) == (
        "bespoke",
        "!",
        "#010203",
    )


def test_malformed_chip_data_falls_back_to_kind_bucket() -> None:
    malformed = _bead(
        "malformed",
        action_data={
            GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈",
            GATE_CHIP_LABEL_ACTION_DATA_KEY: "x" * 33,
            GATE_CHIP_COLOR_ACTION_DATA_KEY: "red",
        },
    )
    non_mapping = _bead("nonmapping", action_data=["not", "a", "mapping"])

    assert _section_for(malformed).label == "Other"
    assert _section_for(non_mapping).label == "Other"


def test_section_order_is_catalog_order_then_due_cleanup_other() -> None:
    rows = [
        (0, _bead("other")),
        (1, _bead("flake", chip_slug="flake")),
        (2, _bead("bug", chip_slug="bug", chip_glyph="⨯", chip_color="#FF5F5F")),
        (3, _bead("cleanup", request_kind="bead_stale_cleanup")),
        (4, _bead("due", request_kind="bead_snooze")),
    ]

    grouped = group_notifications(rows, NOTIFICATION_SECTION_STRATEGIES["bead_type"])

    assert [section.label for section, _rows in grouped] == [
        "Bug",
        "Flaky test",
        "Due",
        "Cleanup",
        "Other",
    ]


def test_group_notifications_preserves_row_order_and_drops_empty_sections() -> None:
    rows = [
        (0, _bead("first", chip_slug="flake")),
        (1, _bead("second", chip_slug="flake")),
        (2, _bead("bug", chip_slug="bug", chip_glyph="⨯", chip_color="#FF5F5F")),
    ]

    grouped = group_notifications(rows, NOTIFICATION_SECTION_STRATEGIES["bead_type"])

    actual = [
        (section.label, [idx for idx, _row in section_rows])
        for section, section_rows in grouped
    ]
    assert actual == [
        ("Bug", [2]),
        ("Flaky test", [0, 1]),
    ]


def test_resolve_tab_section_strategy_respects_config_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        resolve_tab_section_strategy("beads")
        is NOTIFICATION_SECTION_STRATEGIES["bead_type"]
    )

    _use_config(monkeypatch, {"notification_tabs": {"beads": {"grouping": "recent"}}})
    assert resolve_tab_section_strategy("beads") is None

    _use_config(monkeypatch, {"notification_tabs": {"beads": {"grouping": "nope"}}})
    assert resolve_tab_section_strategy("beads") is None

    _use_config(
        monkeypatch,
        {"notification_tabs": {"deployments": {"grouping": "bead_type"}}},
    )
    assert (
        resolve_tab_section_strategy("deployments")
        is NOTIFICATION_SECTION_STRATEGIES["bead_type"]
    )
