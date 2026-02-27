"""Tests for the Lumberjack class."""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
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
    return LumberjackConfig(
        name="test_lj",
        interval=10,
        chops=[ChopConfig(name="hook_checks", description="")],
    )


@pytest.fixture
def axe_config() -> AxeConfig:
    return AxeConfig(max_runners=3, zombie_timeout_seconds=3600, query="")


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
    temp_state_dir: Path, lj_config: LumberjackConfig
) -> None:
    """Test that Lumberjack parses query from config."""
    config = AxeConfig(query='"test"')
    lj = Lumberjack("test_lj", lj_config, config)
    assert lj.parsed_query is not None


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

    lj = Lumberjack("multi", multi_config, axe_config)
    lj._run_tick()

    assert mock_discover.call_count == 2
    assert lj._metrics.chops_executed == 2


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_tick_error_handling(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    lj_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """Test that chop script failures are caught and recorded."""
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = _fail_result()

    lj = Lumberjack("test_lj", lj_config, axe_config)
    lj._run_tick()

    assert lj._metrics.errors_encountered == 1
    assert lj._metrics.cycles_run == 1


@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_tick_missing_script(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    temp_state_dir: Path,
    lj_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """Test that missing chop scripts are recorded as errors."""
    mock_discover.return_value = None

    lj = Lumberjack("test_lj", lj_config, axe_config)
    lj._run_tick()

    assert lj._metrics.errors_encountered == 1
    assert lj._metrics.chops_executed == 0
    assert lj._metrics.cycles_run == 1


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_every_skips_non_matching_cycles(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that chops with run_every > 1 are skipped on non-matching cycles."""
    config = LumberjackConfig(
        name="throttled",
        interval=10,
        chops=[ChopConfig(name="slow_chop", description="", run_every=3)],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = _ok_result()

    lj = Lumberjack("throttled", config, axe_config)

    # Tick 0: cycles_run=0, 0%3==0 → runs
    lj._run_tick()
    assert mock_run.call_count == 1

    # Tick 1: cycles_run=1, 1%3!=0 → skipped
    lj._run_tick()
    assert mock_run.call_count == 1

    # Tick 2: cycles_run=2, 2%3!=0 → skipped
    lj._run_tick()
    assert mock_run.call_count == 1

    # Tick 3: cycles_run=3, 3%3==0 → runs
    lj._run_tick()
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
    """Test that all chops run on the first tick regardless of run_every."""
    config = LumberjackConfig(
        name="first_tick",
        interval=10,
        chops=[
            ChopConfig(name="every_tick", description="", run_every=1),
            ChopConfig(name="every_5th", description="", run_every=5),
            ChopConfig(name="every_10th", description="", run_every=10),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = _ok_result()

    lj = Lumberjack("first_tick", config, axe_config)
    lj._run_tick()

    assert mock_run.call_count == 3


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
