"""Tests for the Lumberjack class."""

import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.config import AxeConfig, LumberjackConfig
from sase.axe.lumberjack import Lumberjack


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Patch AXE_STATE_DIR and LUMBERJACK_STATE_DIR to use a temp directory."""
    state_dir = tmp_path / ".sase" / "axe"
    lj_dir = state_dir / "lumberjacks"
    with (
        patch("sase.axe.state.AXE_STATE_DIR", state_dir),
        patch("sase.axe.state.LUMBERJACK_STATE_DIR", lj_dir),
    ):
        yield state_dir


@pytest.fixture
def lj_config() -> LumberjackConfig:
    return LumberjackConfig(name="test_lj", interval=10, chops=["hook_checks"])


@pytest.fixture
def axe_config() -> AxeConfig:
    return AxeConfig(max_runners=3, zombie_timeout_seconds=3600, query="")


# --- Instantiation Tests ---


def test_lumberjack_instantiation(
    temp_state_dir: Path, lj_config: LumberjackConfig, axe_config: AxeConfig
) -> None:
    """Test that Lumberjack can be instantiated with correct attributes."""
    lj = Lumberjack("test_lj", lj_config, axe_config)
    assert lj.name == "test_lj"
    assert lj.config is lj_config
    assert lj.axe_config is axe_config
    assert lj._running is True
    assert lj._metrics.cycles_run == 0


def test_lumberjack_with_query(
    temp_state_dir: Path, lj_config: LumberjackConfig
) -> None:
    """Test that Lumberjack parses query from config."""
    config = AxeConfig(query='"test"')
    lj = Lumberjack("test_lj", lj_config, config)
    assert lj.parsed_query is not None


# --- Tick Execution Tests ---


@patch("sase.axe.lumberjack.get_chop")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_tick_invokes_chops(
    mock_find: MagicMock,
    mock_get_chop: MagicMock,
    temp_state_dir: Path,
    lj_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """Test that _run_tick invokes each configured chop."""
    mock_chop_func = MagicMock()
    mock_get_chop.return_value = mock_chop_func

    lj = Lumberjack("test_lj", lj_config, axe_config)
    lj._run_tick()

    mock_get_chop.assert_called_once_with("hook_checks")
    mock_chop_func.assert_called_once()
    assert lj._metrics.cycles_run == 1
    assert lj._metrics.chops_executed == 1


@patch("sase.axe.lumberjack.get_chop")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_tick_multiple_chops(
    mock_find: MagicMock,
    mock_get_chop: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that _run_tick invokes multiple chops."""
    multi_config = LumberjackConfig(
        name="multi", interval=5, chops=["hook_checks", "mentor_checks"]
    )
    mock_chop_func = MagicMock()
    mock_get_chop.return_value = mock_chop_func

    lj = Lumberjack("multi", multi_config, axe_config)
    lj._run_tick()

    assert mock_get_chop.call_count == 2
    assert lj._metrics.chops_executed == 2


@patch("sase.axe.lumberjack.get_chop")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_tick_error_handling(
    mock_find: MagicMock,
    mock_get_chop: MagicMock,
    temp_state_dir: Path,
    lj_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """Test that errors in chops are caught and recorded."""
    mock_get_chop.return_value = MagicMock(side_effect=ValueError("boom"))

    lj = Lumberjack("test_lj", lj_config, axe_config)
    lj._run_tick()

    assert lj._metrics.errors_encountered == 1
    assert lj._metrics.cycles_run == 1


# --- Status/Metrics Writing Tests ---


def test_update_status_writes_file(
    temp_state_dir: Path, lj_config: LumberjackConfig, axe_config: AxeConfig
) -> None:
    """Test that _update_status writes a status file."""
    lj = Lumberjack("test_lj", lj_config, axe_config)
    lj._update_status()

    from sase.axe.state import read_lumberjack_status

    status = read_lumberjack_status("test_lj")
    assert status is not None
    assert status.name == "test_lj"
    assert status.pid == os.getpid()
    assert status.status == "running"
    assert status.interval == 10


def test_update_metrics_writes_file(
    temp_state_dir: Path, lj_config: LumberjackConfig, axe_config: AxeConfig
) -> None:
    """Test that _update_metrics writes a metrics file."""
    lj = Lumberjack("test_lj", lj_config, axe_config)
    lj._metrics.cycles_run = 5
    lj._metrics.chops_executed = 15
    lj._update_metrics()

    from sase.axe.state import read_lumberjack_metrics

    metrics = read_lumberjack_metrics("test_lj")
    assert metrics is not None
    assert metrics.cycles_run == 5
    assert metrics.chops_executed == 15


# --- Shutdown Tests ---


def test_handle_shutdown_sets_running_false(
    temp_state_dir: Path, lj_config: LumberjackConfig, axe_config: AxeConfig
) -> None:
    """Test that SIGTERM handler sets _running to False."""
    lj = Lumberjack("test_lj", lj_config, axe_config)
    assert lj._running is True
    lj._handle_shutdown(15, None)
    assert lj._running is False
