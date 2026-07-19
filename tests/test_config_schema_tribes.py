"""Schema coverage for per-tribe ACE display configuration."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from sase.config.inventory import load_config_schema


def test_config_schema_accepts_ace_tribe_display_settings() -> None:
    Draft7Validator(load_config_schema()).validate(
        {
            "ace": {
                "tribes": {
                    "default": {"icon": "🏠"},
                    "my.tribe-1": {
                        "icon": "X",
                        "initially_expanded": False,
                    },
                }
            }
        }
    )


@pytest.mark.parametrize(
    "tribes",
    [
        {"@chop": {"icon": "X"}},
        {"chop space": {"icon": "X"}},
        {"chop": {"unknown": True}},
        {"chop": {"icon": 7}},
        {"chop": {"icon": "x" * 17}},
        {"chop": {"initially_expanded": "false"}},
        {"chop": False},
    ],
)
def test_config_schema_rejects_invalid_ace_tribe_display_settings(
    tribes: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(load_config_schema()).validate({"ace": {"tribes": tribes}})
