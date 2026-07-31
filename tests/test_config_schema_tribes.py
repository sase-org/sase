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
                    "default": {
                        "icon": "🏠",
                        "color": "#ABCDEF",
                        "description": "Home tribe.",
                    },
                    "my.tribe-1": {
                        "icon": "X",
                        "color": "#abcdef",
                        "initially_expanded": False,
                        "description": "A user-defined tribe.",
                    },
                    "empty": {"color": "", "description": "Empty color tribe."},
                }
            }
        }
    )


@pytest.mark.parametrize(
    "tribes",
    [
        {"@chop": {"icon": "X", "description": "Valid."}},
        {"chop space": {"icon": "X", "description": "Valid."}},
        {"chop": {"unknown": True, "description": "Valid."}},
        {"chop": {"icon": 7, "description": "Valid."}},
        {"chop": {"icon": "x" * 17, "description": "Valid."}},
        {"chop": {"color": "#FFF", "description": "Valid."}},
        {"chop": {"color": "FFFFFF", "description": "Valid."}},
        {"chop": {"color": "gold", "description": "Valid."}},
        {"chop": {"color": "#FFFFFF on #000000", "description": "Valid."}},
        {"chop": {"color": 7, "description": "Valid."}},
        {"chop": {"color": None, "description": "Valid."}},
        {"chop": {"initially_expanded": "false", "description": "Valid."}},
        {"chop": False},
        {"chop": {"icon": "X"}},
        {"chop": {"icon": "X", "description": ""}},
        {"chop": {"icon": "X", "description": 7}},
        {"chop": {"icon": "X", "description": "x" * 161}},
    ],
)
def test_config_schema_rejects_invalid_ace_tribe_display_settings(
    tribes: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(load_config_schema()).validate({"ace": {"tribes": tribes}})
