"""Tests for the axe CLI command handlers."""

import argparse
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.cli import (
    handle_axe_chop_list,
    handle_axe_lumberjack_list,
    handle_axe_lumberjack_status,
)
from sase.axe.config import AxeConfig, LumberjackConfig


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Patch state directories for testing."""
    state_dir = tmp_path / ".sase" / "axe"
    lj_dir = state_dir / "lumberjacks"
    shared_dir = state_dir / "shared"
    with (
        patch("sase.axe.state.AXE_STATE_DIR", state_dir),
        patch("sase.axe.state.LUMBERJACK_STATE_DIR", lj_dir),
        patch("sase.axe.state.SHARED_STATE_DIR", shared_dir),
    ):
        yield state_dir


@pytest.fixture
def default_axe_config() -> AxeConfig:
    """Return a default AxeConfig with 4 lumberjacks."""
    from sase.axe.config import _default_lumberjacks

    return AxeConfig(lumberjacks=_default_lumberjacks())


# --- handle_axe_chop_list Tests ---


def test_handle_axe_chop_list_prints_chops(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that chop list prints all 12 registered chop names."""
    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_chop_list(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    lines = [line for line in output.strip().split("\n") if line.strip()]
    assert len(lines) == 12
    assert "hook_checks" in output
    assert "error_digest" in output
    assert "comment_checks" in output


# --- handle_axe_lumberjack_list Tests ---


@patch("sase.axe.cli.load_axe_config")
def test_handle_axe_lumberjack_list_prints_lumberjacks(
    mock_load: MagicMock,
    default_axe_config: AxeConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that lumberjack list prints 4 default lumberjacks."""
    mock_load.return_value = default_axe_config
    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_lumberjack_list(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    lines = [line for line in output.strip().split("\n") if line.strip()]
    assert len(lines) == 4
    assert "hooks" in output
    assert "checks" in output
    assert "comments" in output
    assert "housekeeping" in output


# --- handle_axe_lumberjack_status Tests ---


@patch("sase.axe.cli.load_axe_config")
@patch("sase.axe.cli.read_lumberjack_status", return_value=None)
def test_handle_axe_lumberjack_status_none_running(
    mock_status: MagicMock,
    mock_load: MagicMock,
    default_axe_config: AxeConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test status display when no lumberjacks are running."""
    mock_load.return_value = default_axe_config
    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_lumberjack_status(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    assert "not running" in output


@patch("sase.axe.cli.is_process_running", return_value=True)
@patch("sase.axe.cli.load_axe_config")
@patch("sase.axe.cli.read_lumberjack_status")
def test_handle_axe_lumberjack_status_with_running(
    mock_status: MagicMock,
    mock_load: MagicMock,
    mock_running: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test status display when a lumberjack is running."""
    from sase.axe.state import LumberjackStatus

    mock_load.return_value = AxeConfig(
        lumberjacks={
            "hooks": LumberjackConfig(name="hooks", interval=1, chops=["hook_checks"])
        }
    )
    mock_status.return_value = LumberjackStatus(
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
        handle_axe_lumberjack_status(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    assert "hooks" in output
    assert "running" in output
    assert "12345" in output
    assert "42" in output
