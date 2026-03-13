"""Tests for the axe CLI command handlers."""

import argparse
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.cli import (
    handle_axe_chop_list,
    handle_axe_jack_list,
    handle_axe_jack_status,
)
from sase.axe.config import AxeConfig, ChopConfig, JackConfig

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
        "cl_submitted_checks",
        "comment_checks",
        "error_digest",
        "wait_checks",
    ]
)


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Patch state directories for testing."""
    state_dir = tmp_path / ".sase" / "axe"
    jack_dir = state_dir / "jacks"
    shared_dir = state_dir / "shared"
    with (
        patch("sase.axe.state.AXE_STATE_DIR", state_dir),
        patch("sase.axe.state.JACK_STATE_DIR", jack_dir),
        patch("sase.axe.state.SHARED_STATE_DIR", shared_dir),
    ):
        yield state_dir


@pytest.fixture
def default_axe_config() -> AxeConfig:
    """Return a default AxeConfig with 4 jacks."""
    from sase.axe.config import _parse_jacks

    return AxeConfig(
        jacks=_parse_jacks(
            {
                "hooks": {
                    "interval": 1,
                    "chops": [
                        {"name": "hook_checks", "description": "Check hooks"},
                    ],
                },
                "checks": {
                    "interval": 300,
                    "chops": [
                        {"name": "cl_submitted_checks", "description": "Check CLs"},
                    ],
                },
                "comments": {
                    "interval": 60,
                    "chops": [
                        {"name": "comment_checks", "description": "Check comments"},
                    ],
                },
                "housekeeping": {
                    "interval": 3600,
                    "chops": [
                        {"name": "error_digest", "description": "Digest errors"},
                    ],
                },
            }
        )
    )


# --- handle_axe_chop_list Tests ---


@patch("sase.axe.cli.load_axe_config")
def test_handle_axe_chop_list_deduplicates(
    mock_load: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that chops appearing in multiple jacks are deduplicated."""
    from sase.axe.config import _parse_jacks

    config = AxeConfig(
        jacks=_parse_jacks(
            {
                "jack1": {
                    "interval": 1,
                    "chops": [
                        {"name": "shared_chop", "description": "From jack1"},
                    ],
                },
                "jack2": {
                    "interval": 60,
                    "chops": [
                        {"name": "shared_chop", "description": "From jack2"},
                    ],
                },
            }
        )
    )
    mock_load.return_value = config
    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_chop_list(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    lines = [line for line in output.strip().split("\n") if line.strip()]
    assert len(lines) == 2  # name + indented description
    assert "shared_chop" in output


# --- handle_axe_jack_list Tests ---


@patch("sase.axe.cli.load_axe_config")
def test_handle_axe_jack_list_prints_jacks(
    mock_load: MagicMock,
    default_axe_config: AxeConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that jack list prints 4 default jacks."""
    mock_load.return_value = default_axe_config
    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_jack_list(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    lines = [line for line in output.strip().split("\n") if line.strip()]
    # 4 jacks × (name + interval + "chops:" + 1 chop) = 16 non-empty lines
    assert len(lines) == 16
    assert "hooks" in output
    assert "checks" in output
    assert "comments" in output
    assert "housekeeping" in output
    assert "interval:" in output
    assert "chops:" in output


# --- handle_axe_jack_status Tests ---


@patch("sase.axe.cli.load_axe_config")
@patch("sase.axe.cli.read_jack_status", return_value=None)
def test_handle_axe_jack_status_none_running(
    mock_status: MagicMock,
    mock_load: MagicMock,
    default_axe_config: AxeConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test status display when no jacks are running."""
    mock_load.return_value = default_axe_config
    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_jack_status(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    assert "not running" in output


@patch("sase.axe.cli.is_process_running", return_value=True)
@patch("sase.axe.cli.load_axe_config")
@patch("sase.axe.cli.read_jack_status")
def test_handle_axe_jack_status_with_running(
    mock_status: MagicMock,
    mock_load: MagicMock,
    mock_running: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test status display when a jack is running."""
    from sase.axe.state import JackStatus

    mock_load.return_value = AxeConfig(
        jacks={
            "hooks": JackConfig(
                name="hooks",
                interval=1,
                chops=[ChopConfig(name="hook_checks", description="Check hooks")],
            )
        }
    )
    mock_status.return_value = JackStatus(
        name="hooks",
        pid=12345,
        started_at="2026-01-01T00:00:00",
        status="running",
        interval=1,
        chops=["hook_checks"],
        cycles_run=42,
        errors_encountered=0,
        uptime_seconds=100,
    )

    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_jack_status(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    assert "hooks" in output
    assert "running" in output
    assert "12345" in output
    assert "42" in output
