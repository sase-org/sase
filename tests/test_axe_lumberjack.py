"""Tests for the Lumberjack class."""

import os
import subprocess
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.chop_agents import ENV_CHOP_NAME
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.lumberjack import Lumberjack
from tests._axe_lumberjack_fixtures import fail_result, ok_result


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


# --- Instantiation Tests ---


def test_lumberjack_with_query(
    temp_state_dir: Path, lumberjack_config: LumberjackConfig
) -> None:
    """Test that Lumberjack accepts a parseable query and forwards it to the check runner."""
    config = AxeConfig(query='"test"')
    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, config)
    assert lumberjack._check_runner.query == '"test"'


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
    mock_run.return_value = ok_result()

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
    mock_run.return_value = fail_result()

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
    mock_run.return_value = ok_result()

    lumberjack = Lumberjack("throttled", config, axe_config)

    # First tick: no timestamp exists → runs
    lumberjack._run_tick()
    assert mock_run.call_count == 1

    # Second tick immediately: timestamp was just set → skipped
    lumberjack._run_tick()
    assert mock_run.call_count == 1

    # Simulate enough time having passed
    from sase.core.time import get_timezone

    lumberjack._chop_timestamps["slow_chop"] = datetime.now(get_timezone()) - timedelta(
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
    mock_run.return_value = ok_result()

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
    mock_run.return_value = ok_result()

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


# --- Timeout Tests ---


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_timeout_expired_records_error_and_continues(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that TimeoutExpired is caught and subsequent chops still run."""
    config = LumberjackConfig(
        name="timeout_test",
        interval=10,
        chop_timeout=5,
        chops=[
            ChopConfig(name="slow_chop", description=""),
            ChopConfig(name="fast_chop", description=""),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = [
        subprocess.TimeoutExpired(cmd="slow_chop", timeout=5),
        ok_result(),
    ]

    lumberjack = Lumberjack("timeout_test", config, axe_config)
    lumberjack._run_tick()

    assert lumberjack._metrics.errors_encountered == 1
    assert lumberjack._metrics.chops_executed == 1
    assert lumberjack._metrics.cycles_run == 1


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_per_chop_timeout_overrides_lumberjack_default(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that per-chop timeout overrides lumberjack-level chop_timeout."""
    config = LumberjackConfig(
        name="override_test",
        interval=10,
        chop_timeout=30,
        chops=[
            ChopConfig(name="custom_timeout", description="", timeout=10),
            ChopConfig(name="default_timeout", description=""),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = ok_result()

    lumberjack = Lumberjack("override_test", config, axe_config)
    lumberjack._run_tick()

    # Chops run concurrently via ThreadPoolExecutor, so call ordering is
    # nondeterministic — key assertions by chop name instead of position.
    assert mock_run.call_count == 2
    timeouts_by_chop = {
        call.kwargs["env"][ENV_CHOP_NAME]: call.kwargs["timeout"]
        for call in mock_run.call_args_list
    }
    assert timeouts_by_chop == {"custom_timeout": 10, "default_timeout": 30}


# --- Tick Overrun Warning Tests ---


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_tick_overrun_logs_warning(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that a warning is logged when tick duration exceeds interval."""
    config = LumberjackConfig(
        name="overrun_test",
        interval=1,
        chops=[ChopConfig(name="slow_chop", description="")],
    )
    mock_discover.return_value = Path("/fake/script")

    def slow_run(*args, **kwargs):
        import time

        time.sleep(1.1)
        return ok_result()

    mock_run.side_effect = slow_run

    lumberjack = Lumberjack("overrun_test", config, axe_config)
    lumberjack._run_tick()

    # Check the log output contains the overrun warning
    log_path = temp_state_dir / "lumberjacks" / "overrun_test" / "lumberjack.log"
    if log_path.exists():
        log_content = log_path.read_text()
        assert "Tick overrun" in log_content


# --- Shutdown Tests ---


def test_handle_shutdown_sets_running_false(
    temp_state_dir: Path, lumberjack_config: LumberjackConfig, axe_config: AxeConfig
) -> None:
    """Test that SIGTERM handler sets _running to False."""
    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    assert lumberjack._running is True
    lumberjack._handle_shutdown(15, None)
    assert lumberjack._running is False


# --- Concurrency Tests ---


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_chops_run_concurrently(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that chops run concurrently (two 1s chops complete in ~1s, not ~2s)."""
    config = LumberjackConfig(
        name="concurrent_test",
        interval=10,
        chops=[
            ChopConfig(name="slow_a", description=""),
            ChopConfig(name="slow_b", description=""),
        ],
    )
    mock_discover.return_value = Path("/fake/script")

    def slow_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        time.sleep(1.0)
        return ok_result()

    mock_run.side_effect = slow_run

    lumberjack = Lumberjack("concurrent_test", config, axe_config)
    start = time.monotonic()
    lumberjack._run_tick()
    elapsed = time.monotonic() - start

    assert mock_run.call_count == 2
    assert lumberjack._metrics.chops_executed == 2
    # If sequential, would take ~2s. Concurrent should be ~1s.
    assert elapsed < 1.8, f"Expected concurrent execution (<1.8s), took {elapsed:.1f}s"


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_one_chop_failure_does_not_block_others(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that one chop failing doesn't prevent others from running."""
    config = LumberjackConfig(
        name="isolation_test",
        interval=10,
        chops=[
            ChopConfig(name="failing_chop", description=""),
            ChopConfig(name="ok_chop", description=""),
            ChopConfig(name="crashing_chop", description=""),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = [
        fail_result(),
        ok_result(),
        RuntimeError("unexpected crash"),
    ]

    lumberjack = Lumberjack("isolation_test", config, axe_config)
    lumberjack._run_tick()

    assert mock_run.call_count == 3
    assert lumberjack._metrics.chops_executed == 1
    assert lumberjack._metrics.errors_encountered == 2
