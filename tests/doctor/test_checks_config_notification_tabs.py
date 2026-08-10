"""Tests for notification tab config checks."""

from __future__ import annotations

from typing import Any

import pytest

from sase.doctor import checks_config
from sase.doctor.checks_config_notification_tabs import (
    check_config_notification_tabs,
)
from sase.doctor.runner import default_doctor_context


def _use_config(monkeypatch: pytest.MonkeyPatch, ace: dict[str, Any]) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_config_notification_tabs.load_merged_config",
        lambda: {"ace": ace},
    )


def test_unique_notification_tab_icons_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_config(
        monkeypatch,
        {
            "notification_tabs": {
                "beads": {"icon": "◈"},
                "done": {"icon": "#"},
            }
        },
    )

    check = check_config_notification_tabs()

    assert check.status == "OK"
    assert check.data["configured_icon_count"] == 2


def test_duplicate_notification_tab_icons_warn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(
        monkeypatch,
        {
            "notification_tabs": {
                "beads": {"icon": "◈"},
                "review": {"icon": "◈"},
            }
        },
    )

    check = check_config_notification_tabs()

    assert check.status == "WARN"
    assert check.id == "config.notification_tabs"
    assert check.details == (
        "icon '◈' is configured by notification tabs: beads, review",
    )
    assert check.data["duplicate_count"] == 1


def test_blank_and_invalid_notification_tab_icons_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(
        monkeypatch,
        {
            "notification_tabs": {
                "blank": {"icon": ""},
                "wide": {"icon": "你你"},
                "not-an-object": "◈",
            }
        },
    )

    check = check_config_notification_tabs()

    assert check.status == "OK"
    assert check.data["configured_icon_count"] == 0


def test_notification_tab_icon_check_is_registered() -> None:
    specs = checks_config.config_check_specs(default_doctor_context())

    assert "config.notification_tabs" in {spec.id for spec in specs}
