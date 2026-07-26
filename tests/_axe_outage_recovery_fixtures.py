"""Shared fixtures for axe outage-recovery tests."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.config import AxeConfig, LumberjackConfig


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Create a temporary axe state directory for testing."""
    state_dir = tmp_path / ".sase" / "axe"
    lumberjack_dir = state_dir / "lumberjacks"
    log_dir = state_dir / "logs"
    state_dir.mkdir(parents=True, exist_ok=True)
    lumberjack_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    with (
        patch("sase.axe.state.axe_state_dir", return_value=state_dir),
        patch("sase.axe.state.jack_state_dir", return_value=lumberjack_dir),
    ):
        yield state_dir


@pytest.fixture
def axe_config() -> AxeConfig:
    return AxeConfig(
        max_hook_runners=3,
        max_agent_runners=3,
        zombie_timeout_seconds=7200,
        query="",
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                description="Run hook recovery checks",
                interval=5,
            ),
            "waits": LumberjackConfig(
                name="waits",
                description="Run wait recovery checks",
                interval=5,
            ),
        },
    )
