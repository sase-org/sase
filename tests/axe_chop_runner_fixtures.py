"""Pytest fixtures for chop runner tests."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.config import AxeConfig


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    state_dir = tmp_path / ".sase" / "axe"
    lumberjack_dir = state_dir / "lumberjacks"
    with (
        patch("sase.axe.state.AXE_STATE_DIR", state_dir),
        patch("sase.axe.state.JACK_STATE_DIR", lumberjack_dir),
    ):
        yield state_dir


@pytest.fixture
def axe_config() -> AxeConfig:
    return AxeConfig(
        max_hook_runners=3,
        max_agent_runners=3,
        zombie_timeout_seconds=3600,
        query="",
    )
