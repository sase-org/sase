"""Config tab fixtures for Config Center PNG visual snapshots."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.modals import config_pane as cp
from sase.config.core import ConfigLayer
from sase.config.inventory import build_config_inventory, config_field_model

_LONG_QUERY = (
    "status:running and (agent:planner or agent:coder) and "
    "project:visual_demo and not tribe:archived and updated_after:2026-01-01"
)


def _large_lumberjack_value(count: int = 24) -> dict[str, Any]:
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


def _config_schema(*, object_value: bool = False) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "timezone": {
                "type": "string",
                "default": "America/New_York",
                "description": "IANA timezone used for all dates.",
            },
            "use_chezmoi": {
                "type": "boolean",
                "default": False,
                "description": "Manage home-dir config via chezmoi.",
            },
            "mode": {
                "type": "string",
                "enum": ["auto", "manual", "off"],
                "default": "auto",
                "description": "Default automation mode.",
            },
            "axe": {
                "type": "object",
                "additionalProperties": False,
                "description": "Background AXE engine settings.",
                "properties": {
                    "max_hook_runners": {
                        "type": "integer",
                        "default": 3,
                        "description": "Max concurrent hook runners.",
                    },
                    "query": {
                        "type": "string",
                        "default": "",
                        "description": "Default AXE query filter.",
                    },
                    "chop_script_dirs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                        "description": "Directories scanned for chop scripts.",
                    },
                },
            },
            **(
                {
                    "ace": {
                        "type": "object",
                        "additionalProperties": False,
                        "description": "ACE TUI settings.",
                        "properties": {
                            "lumberjack": {
                                "type": "object",
                                "additionalProperties": {
                                    "type": "object",
                                    "additionalProperties": True,
                                },
                                "default": _large_lumberjack_value(),
                                "description": "Named background lumberjack jobs.",
                            },
                        },
                    }
                }
                if object_value
                else {}
            ),
            "linked_repos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
                "default": [],
                "description": "Linked sibling repositories.",
            },
            "sibling_repos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
                "description": "Deprecated alias for linked_repos.",
            },
        },
    }


def _config_layers(
    *, long_value: bool = False, object_value: bool = False
) -> list[ConfigLayer]:
    user_axe: dict[str, Any] = {"max_hook_runners": 5}
    if long_value:
        user_axe["query"] = _LONG_QUERY
    return [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={
                "timezone": "America/New_York",
                "use_chezmoi": False,
                "mode": "auto",
                "axe": {
                    "max_hook_runners": 3,
                    "query": "",
                    "chop_script_dirs": ["builtin"],
                },
                **(
                    {
                        "ace": {
                            "lumberjack": _large_lumberjack_value(),
                        }
                    }
                    if object_value
                    else {}
                ),
                "linked_repos": [{"name": "core"}],
            },
        ),
        ConfigLayer(
            name="user",
            path="/home/visual/.config/sase/sase.yml",
            exists=True,
            list_strategy="replace",
            data={
                "timezone": "US/Pacific",
                "mode": "manual",
                "axe": user_axe,
                **(
                    {
                        "ace": {
                            "lumberjack": {
                                **_large_lumberjack_value(),
                                "recent_audit": {
                                    "description": "Audit saves.",
                                    "interval": "900s",
                                },
                            },
                        }
                    }
                    if object_value
                    else {}
                ),
                "sibling_repos": [{"name": "legacy"}],
            },
        ),
        ConfigLayer(
            name="overlay:sase_work.yml",
            path="/home/visual/.config/sase/sase_work.yml",
            exists=True,
            list_strategy="concatenate",
            data={"axe": {"chop_script_dirs": ["work"]}},
        ),
        ConfigLayer(
            name="overlay:missing.yml",
            path="/home/visual/.config/sase/missing.yml",
            exists=False,
            list_strategy="concatenate",
            data={},
        ),
    ]


def _build_view(schema: dict[str, Any], layers: list[ConfigLayer]) -> cp.ConfigPaneView:
    with patch(
        "sase.config.inventory.load_config_layers",
        return_value=layers,
    ):
        inventory = build_config_inventory(schema=schema)
    field_model = config_field_model(schema)
    return cp.ConfigPaneView.build(field_model, inventory)


def _patch_config_view(
    monkeypatch: pytest.MonkeyPatch, view: cp.ConfigPaneView | None
) -> None:
    result = cp._LoadResult(view=view, error=None, token=("visual", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kw: result)
