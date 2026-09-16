"""Shared fixtures for sase.axe CLI tests."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.config import AxeConfig

ALL_12_CHOP_NAMES = sorted(
    [
        "hook_checks",
        "mentor_checks",
        "workflow_checks",
        "pending_checks_poll",
        "comment_zombie_checks",
        "suffix_transforms",
        "orphan_cleanup",
        "stale_running_cleanup",
        "pr_submitted_checks",
        "comment_checks",
        "error_digest",
        "wait_checks",
    ]
)


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Patch state directories for testing."""
    state_dir = tmp_path / ".sase" / "axe"
    lumberjack_dir = state_dir / "lumberjacks"
    shared_dir = state_dir / "shared"
    with (
        patch("sase.axe.state.axe_state_dir", return_value=state_dir),
        patch("sase.axe.state.jack_state_dir", return_value=lumberjack_dir),
        patch("sase.axe.state.shared_state_dir", return_value=shared_dir),
    ):
        yield state_dir


@pytest.fixture
def default_axe_config() -> AxeConfig:
    """Return a default AxeConfig with 4 lumberjacks."""
    from sase.axe.config import _parse_lumberjacks

    return AxeConfig(
        lumberjacks=_parse_lumberjacks(
            {
                "hooks": {
                    "interval": 1,
                    "description": "Fast lane that advances hook lifecycle state",
                    "chops": [
                        {"name": "hook_checks", "description": "Check hooks"},
                    ],
                },
                "checks": {
                    "interval": 300,
                    "description": "Poll slower PR-submission checks",
                    "chops": [
                        {
                            "name": "pr_submitted_checks",
                            "description": "Check Patches",
                        },
                    ],
                },
                "comments": {
                    "interval": 60,
                    "description": "Start critique-comment checks for mailed PRs",
                    "chops": [
                        {"name": "comment_checks", "description": "Check comments"},
                    ],
                },
                "housekeeping": {
                    "description": "Run hourly housekeeping checks",
                    "interval": 3600,
                    "chops": [
                        {"name": "error_digest", "description": "Digest errors"},
                    ],
                },
            }
        )
    )
