"""Tests for the Lumberjack class."""

import os
import subprocess
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.lumberjack import Lumberjack


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Patch AXE_STATE_DIR and JACK_STATE_DIR to use a temp directory."""
    state_dir = tmp_path / ".sase" / "axe"
    lumberjack_dir = state_dir / "lumberjacks"
    with (
        patch("sase.axe.state.AXE_STATE_DIR", state_dir),
        patch("sase.axe.state.JACK_STATE_DIR", lumberjack_dir),
    ):
        yield state_dir


@pytest.fixture
def lumberjack_config() -> LumberjackConfig:
    return LumberjackConfig(
        name="test_lumberjack",
        interval=10,
        chops=[ChopConfig(name="hook_checks", description="")],
    )


@pytest.fixture
def axe_config() -> AxeConfig:
    return AxeConfig(
        max_hook_runners=3, max_agent_runners=3, zombie_timeout_seconds=3600, query=""
    )


def _ok_result() -> subprocess.CompletedProcess[str]:
    """Return a successful CompletedProcess for mocking."""
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def _fail_result(
    code: int = 1, stderr: str = "error"
) -> subprocess.CompletedProcess[str]:
    """Return a failed CompletedProcess for mocking."""
    return subprocess.CompletedProcess(
        args=[], returncode=code, stdout="", stderr=stderr
    )


# --- Instantiation Tests ---


def test_lumberjack_with_query(
    temp_state_dir: Path, lumberjack_config: LumberjackConfig
) -> None:
    """Test that Lumberjack parses query from config."""
    config = AxeConfig(query='"test"')
    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, config)
    assert lumberjack.parsed_query is not None


# --- Tick Execution Tests ---


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_tick_multiple_chops(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that _run_tick invokes multiple chop scripts."""
    multi_config = LumberjackConfig(
        name="multi",
        interval=5,
        chops=[
            ChopConfig(name="hook_checks", description=""),
            ChopConfig(name="mentor_checks", description=""),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = _ok_result()

    lumberjack = Lumberjack("multi", multi_config, axe_config)
    lumberjack._run_tick()

    assert mock_discover.call_count == 2
    assert lumberjack._metrics.chops_executed == 2


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_tick_error_handling(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    lumberjack_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """Test that chop script failures are caught and recorded."""
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = _fail_result()

    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._run_tick()

    assert lumberjack._metrics.errors_encountered == 1
    assert lumberjack._metrics.cycles_run == 1


@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_tick_missing_script(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    temp_state_dir: Path,
    lumberjack_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """Test that missing chop scripts are recorded as errors."""
    mock_discover.return_value = None

    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._run_tick()

    assert lumberjack._metrics.errors_encountered == 1
    assert lumberjack._metrics.chops_executed == 0
    assert lumberjack._metrics.cycles_run == 1


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_every_skips_when_not_enough_time_elapsed(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that chops with run_every are skipped when not enough time has elapsed."""
    config = LumberjackConfig(
        name="throttled",
        interval=10,
        chops=[ChopConfig(name="slow_chop", description="", run_every=3600)],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = _ok_result()

    lumberjack = Lumberjack("throttled", config, axe_config)

    # First tick: no timestamp exists → runs
    lumberjack._run_tick()
    assert mock_run.call_count == 1

    # Second tick immediately: timestamp was just set → skipped
    lumberjack._run_tick()
    assert mock_run.call_count == 1

    # Simulate enough time having passed
    from sase.sase_utils import EASTERN_TZ

    lumberjack._chop_timestamps["slow_chop"] = datetime.now(EASTERN_TZ) - timedelta(
        seconds=3601
    )
    lumberjack._run_tick()
    assert mock_run.call_count == 2


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_all_chops_run_on_first_tick(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that all chops run on the first tick (no prior timestamps)."""
    config = LumberjackConfig(
        name="first_tick",
        interval=10,
        chops=[
            ChopConfig(name="every_tick", description=""),
            ChopConfig(name="hourly", description="", run_every=3600),
            ChopConfig(name="daily", description="", run_every=86400),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = _ok_result()

    lumberjack = Lumberjack("first_tick", config, axe_config)
    lumberjack._run_tick()

    assert mock_run.call_count == 3


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_chops_without_run_every_run_every_tick(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that chops without run_every always run."""
    config = LumberjackConfig(
        name="always",
        interval=10,
        chops=[ChopConfig(name="always_chop", description="")],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = _ok_result()

    lumberjack = Lumberjack("always", config, axe_config)
    lumberjack._run_tick()
    lumberjack._run_tick()
    lumberjack._run_tick()

    assert mock_run.call_count == 3


# --- Status/Metrics Writing Tests ---


def test_update_status_writes_file(
    temp_state_dir: Path, lumberjack_config: LumberjackConfig, axe_config: AxeConfig
) -> None:
    """Test that _update_status writes a status file."""
    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._update_status()

    from sase.axe.state import read_lumberjack_status

    status = read_lumberjack_status("test_lumberjack")
    assert status is not None
    assert status.name == "test_lumberjack"
    assert status.pid == os.getpid()
    assert status.status == "running"
    assert status.interval == 10


def test_update_metrics_writes_file(
    temp_state_dir: Path, lumberjack_config: LumberjackConfig, axe_config: AxeConfig
) -> None:
    """Test that _update_metrics writes a metrics file."""
    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._metrics.cycles_run = 5
    lumberjack._metrics.chops_executed = 15
    lumberjack._update_metrics()

    from sase.axe.state import read_lumberjack_metrics

    metrics = read_lumberjack_metrics("test_lumberjack")
    assert metrics is not None
    assert metrics.cycles_run == 5
    assert metrics.chops_executed == 15


# --- Shutdown Tests ---


def test_handle_shutdown_sets_running_false(
    temp_state_dir: Path, lumberjack_config: LumberjackConfig, axe_config: AxeConfig
) -> None:
    """Test that SIGTERM handler sets _running to False."""
    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    assert lumberjack._running is True
    lumberjack._handle_shutdown(15, None)
    assert lumberjack._running is False
