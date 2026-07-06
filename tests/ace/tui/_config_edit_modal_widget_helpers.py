"""Shared fixtures for Config Center edit modal widget tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals.config_edit_modal import ConfigEditModal
from sase.config.core import ConfigLayer
from sase.config.inventory import build_config_inventory, config_field_model


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "timezone": {
            "type": "string",
            "default": "America/New_York",
            "description": "IANA timezone.",
        },
        "mode": {
            "type": "string",
            "enum": ["auto", "manual", "off"],
            "default": "auto",
        },
        "notes": {
            "type": "string",
            "default": "line 1\nline 2",
        },
        "use_chezmoi": {"type": "boolean", "default": False},
        "axe": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "max_hook_runners": {
                    "type": "integer",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 9,
                },
                "chop_script_dirs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
            },
        },
        "ace": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "lumberjack": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                    "default": {
                        "checks": {
                            "description": "Run checks.",
                            "interval": "300s",
                        }
                    },
                },
            },
        },
        "linked_repos": {
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}}},
            "default": [],
        },
        "sibling_repos": {
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}}},
        },
    },
}


def config_edit_view(
    tmp_path: Path, user_data: dict[str, Any]
) -> tuple[cp.ConfigPaneView, Path]:
    """A view over a [default, user, overlay] stack backed by a real user file."""
    user_file = tmp_path / "sase.yml"
    user_file.write_text(yaml.safe_dump(user_data), encoding="utf-8")
    overlay_file = tmp_path / "sase_extra.yml"
    overlay_file.write_text("axe:\n  chop_script_dirs:\n    - over\n", encoding="utf-8")
    layers = [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={
                "timezone": "America/New_York",
                "mode": "auto",
                "notes": "line 1\nline 2",
                "use_chezmoi": False,
                "axe": {"max_hook_runners": 3, "chop_script_dirs": []},
                "ace": {
                    "lumberjack": {
                        "checks": {
                            "description": "Run checks.",
                            "interval": "300s",
                        }
                    }
                },
                "linked_repos": [],
            },
        ),
        ConfigLayer(
            name="user",
            path=str(user_file),
            exists=True,
            list_strategy="replace",
            data=user_data,
        ),
        ConfigLayer(
            name="overlay:sase_extra.yml",
            path=str(overlay_file),
            exists=True,
            list_strategy="concatenate",
            data={"axe": {"chop_script_dirs": ["over"]}},
        ),
    ]
    with patch("sase.config.inventory.load_config_layers", return_value=layers):
        inventory = build_config_inventory(schema=_SCHEMA)
    field_model = config_field_model(schema=_SCHEMA)
    return cp.ConfigPaneView.build(field_model, inventory), user_file


def large_lumberjack_value(count: int = 50) -> dict[str, Any]:
    return {
        f"job_{index:03d}": {
            "description": (
                f"Background maintenance job {index:03d} with a deliberately "
                "long sentence that should not soft-wrap inside the edit modal."
            ),
            "interval": f"{300 + index}s",
            "command": f"sase axe chop job_{index:03d}",
        }
        for index in range(count)
    }


async def open_config_edit_modal(page: AcePage, modal: ConfigEditModal) -> list[Any]:
    """Push *modal* and return a list that receives its dismiss result."""
    result: list[Any] = []
    page.app.push_screen(modal, result.append)
    await page.expect_modal("ConfigEditModal")
    await page.pause()
    return result


@pytest.fixture(autouse=True)
def _no_chezmoi() -> Any:
    """Pin chezmoi off so writes land in the temp file, not a source tree."""
    with patch("sase.config.edit.get_use_chezmoi", return_value=False):
        yield
