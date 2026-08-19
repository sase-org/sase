"""Schema coverage for per-tab notification indicator configuration."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from sase.config.inventory import load_config_schema


def test_config_schema_accepts_ace_notification_tab_settings() -> None:
    Draft7Validator(load_config_schema()).validate(
        {
            "ace": {
                "notification_tabs": {
                    "hitl": {"color": "#FF8700", "icon": "⚑"},
                    "snoozed": {"color": "#6c6c6c"},
                    "my-tag.1": {"color": "", "icon": ""},
                    "beads": {},
                    "deployments": {"icon": "🚀"},
                },
                "notification_indicator_max_counts": 6,
            }
        }
    )


def test_the_bundled_defaults_validate_against_the_schema() -> None:
    from sase.config.core import _load_default_config

    ace = _load_default_config()["ace"]

    Draft7Validator(load_config_schema()).validate(
        {
            "ace": {
                "notification_tabs": ace["notification_tabs"],
                "notification_indicator_max_counts": ace[
                    "notification_indicator_max_counts"
                ],
            }
        }
    )


@pytest.mark.parametrize(
    "tabs",
    [
        {"my tab": {"color": "#FFFFFF"}},
        {"hitl": {"color": "#FFF"}},
        {"hitl": {"color": "FFFFFF"}},
        {"hitl": {"color": "gold"}},
        {"hitl": {"color": 7}},
        {"hitl": {"icon": 7}},
        {"hitl": {"icon": "x" * 33}},
        {"hitl": {"unknown": True}},
        {"hitl": False},
    ],
)
def test_config_schema_rejects_invalid_notification_tab_settings(
    tabs: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(load_config_schema()).validate(
            {"ace": {"notification_tabs": tabs}}
        )


def test_config_schema_accepts_notification_tab_priorities() -> None:
    Draft7Validator(load_config_schema()).validate(
        {
            "ace": {
                "notification_tabs": {
                    "beads": {"priority": 0},
                    "x": {"priority": -1000},
                }
            }
        }
    )


@pytest.mark.parametrize("priority", ["high", 1001, -1001, 1.5])
def test_config_schema_rejects_invalid_notification_tab_priorities(
    priority: object,
) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(load_config_schema()).validate(
            {"ace": {"notification_tabs": {"hitl": {"priority": priority}}}}
        )


@pytest.mark.parametrize("maximum", [0, -1, "4", 1.5])
def test_config_schema_rejects_an_unusable_indicator_maximum(
    maximum: object,
) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(load_config_schema()).validate(
            {"ace": {"notification_indicator_max_counts": maximum}}
        )
