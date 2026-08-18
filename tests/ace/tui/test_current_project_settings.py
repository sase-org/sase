"""ACE ``ace.current_project`` configuration tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.ace.tui.app import AceApp
from sase.ace.tui.current_project_settings import (
    CurrentProjectSettings,
    parse_current_project_settings,
)


def test_current_project_settings_defaults() -> None:
    assert parse_current_project_settings(None) == CurrentProjectSettings()
    assert parse_current_project_settings({}) == CurrentProjectSettings(
        indicator=True,
        seed_filters=True,
        seed_agents_query=False,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("indicator", False),
        ("seed_filters", False),
        ("seed_agents_query", True),
    ],
)
def test_current_project_settings_overrides_each_field(field: str, value: bool) -> None:
    settings = parse_current_project_settings({"current_project": {field: value}})

    expected = CurrentProjectSettings()
    assert getattr(settings, field) is value
    for other in ("indicator", "seed_filters", "seed_agents_query"):
        if other != field:
            assert getattr(settings, other) is getattr(expected, other)


def test_current_project_settings_overrides_all_fields() -> None:
    settings = parse_current_project_settings(
        {
            "current_project": {
                "indicator": False,
                "seed_filters": False,
                "seed_agents_query": True,
            }
        }
    )

    assert settings == CurrentProjectSettings(
        indicator=False,
        seed_filters=False,
        seed_agents_query=True,
    )


@pytest.mark.parametrize(
    "ace_cfg",
    [None, "ace", 1, True, False, [], object()],
)
def test_current_project_settings_rejects_non_mapping_ace_cfg(ace_cfg: object) -> None:
    assert parse_current_project_settings(ace_cfg) == CurrentProjectSettings()


@pytest.mark.parametrize(
    "value",
    [None, "true", "false", "yes", 0, 1, [], {}, object()],
)
def test_current_project_settings_rejects_non_boolean_fields(value: object) -> None:
    settings = parse_current_project_settings(
        {
            "current_project": {
                "indicator": value,
                "seed_filters": value,
                "seed_agents_query": value,
            }
        }
    )

    assert settings == CurrentProjectSettings()


@pytest.mark.parametrize(
    "block",
    [None, "yes", 1, True, False, []],
)
def test_current_project_settings_rejects_non_mapping_block(block: object) -> None:
    assert (
        parse_current_project_settings({"current_project": block})
        == CurrentProjectSettings()
    )


def test_current_project_settings_mixed_valid_and_malformed() -> None:
    settings = parse_current_project_settings(
        {
            "current_project": {
                "indicator": False,
                "seed_filters": "no",
                "seed_agents_query": True,
            }
        }
    )

    assert settings == CurrentProjectSettings(
        indicator=False,
        seed_filters=True,
        seed_agents_query=True,
    )


def test_startup_loads_current_project_settings_from_merged_config() -> None:
    with patch(
        "sase.config.load_merged_config",
        return_value={
            "ace": {
                "current_project": {
                    "indicator": False,
                    "seed_filters": False,
                    "seed_agents_query": True,
                }
            }
        },
    ):
        app = AceApp()

    assert app._current_project_settings == CurrentProjectSettings(
        indicator=False,
        seed_filters=False,
        seed_agents_query=True,
    )
