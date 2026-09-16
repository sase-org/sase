"""Tests for the ``handle_axe_chop_list`` CLI command handler."""

import argparse
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.cli import handle_axe_chop_list
from sase.axe.config import AxeConfig


@patch("sase.axe.cli.load_axe_config")
def test_handle_axe_chop_list_renders_configured_chops(
    mock_load: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The list view renders one configured-chop row per lumberjack."""
    from sase.axe.config import _parse_lumberjacks

    config = AxeConfig(
        lumberjacks=_parse_lumberjacks(
            {
                "lumberjack1": {
                    "description": "Run first shared-chop checks",
                    "interval": 1,
                    "chops": [
                        {"name": "shared_chop", "description": "From lumberjack1"},
                    ],
                },
                "lumberjack2": {
                    "description": "Run second shared-chop checks",
                    "interval": 60,
                    "chops": [
                        {"name": "shared_chop", "description": "From lumberjack2"},
                    ],
                },
            }
        )
    )
    mock_load.return_value = config
    args = argparse.Namespace(json=False, available=False, verbose=False)
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_chop_list(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    assert "shared_chop" in output
    assert "Configured Jobs" in output
