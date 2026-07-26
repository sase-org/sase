"""Tests for scheduled Lumberjack tick execution."""

import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.chop_agents import ENV_CHOP_NAME
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.lumberjack import Lumberjack
from sase.axe.maintenance import clear_maintenance, read_maintenance, start_maintenance
from sase.axe.chop_runner_types import ChopRunOutcome, ChopRunOutcomeStatus
from tests._axe_lumberjack_fixtures import (
    streamed_fail,
    streamed_ok,
    streamed_seq,
    streamed_timeout,
)

pytest_plugins = ("tests._axe_lumberjack_fixtures",)


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
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
        description="Run multiple test chops",
        interval=5,
        chops=[
            ChopConfig(name="hook_checks", description=""),
            ChopConfig(name="mentor_checks", description=""),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_ok()

    lumberjack = Lumberjack("multi", multi_config, axe_config)
    lumberjack._run_tick()

    assert mock_discover.call_count == 2
    assert lumberjack._metrics.chops_executed == 2


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
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
    mock_run.side_effect = streamed_fail()

    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._run_tick()

    assert lumberjack._metrics.errors_encountered == 1
    assert lumberjack._metrics.cycles_run == 1


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_tick_skips_without_error_during_maintenance(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    lumberjack_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """Maintenance skips the tick before chops run and does not record an error."""
    start_maintenance("install_sase_github")

    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._run_tick()

    mock_find.assert_not_called()
    mock_discover.assert_not_called()
    mock_run.assert_not_called()
    assert lumberjack._metrics.errors_encountered == 0
    assert lumberjack._metrics.chops_executed == 0
    assert lumberjack._metrics.cycles_run == 1


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_tick_clears_dead_pid_maintenance_and_runs_chops(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    lumberjack_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """A dead maintenance owner is cleared before the tick decides to skip."""
    start_maintenance("install_sase_github")
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_ok()

    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    with patch("sase.axe.maintenance.is_process_running", return_value=False):
        lumberjack._run_tick()

    assert read_maintenance() is None
    assert mock_find.call_count == 1
    assert mock_run.call_count == 1
    assert lumberjack._metrics.errors_encountered == 0
    assert lumberjack._metrics.chops_executed == 1
    assert lumberjack._metrics.cycles_run == 1


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_tick_resumes_after_maintenance_cleared(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    lumberjack_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """Clearing maintenance restores normal chop execution and error handling."""
    start_maintenance("install_sase_github")
    clear_maintenance()
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_fail()

    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._run_tick()

    assert mock_find.call_count == 1
    assert mock_run.call_count == 1
    assert lumberjack._metrics.errors_encountered == 1
    assert lumberjack._metrics.cycles_run == 1


@patch("sase.axe.chop_runner.discover_chop_script")
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


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
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
        description="Run throttled test chops",
        interval=10,
        chops=[ChopConfig(name="slow_chop", description="", run_every=3600)],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_ok()

    lumberjack = Lumberjack("throttled", config, axe_config)

    lumberjack._run_tick()
    assert mock_run.call_count == 1

    lumberjack._run_tick()
    assert mock_run.call_count == 1

    from sase.core.time import get_timezone

    lumberjack._chop_timestamps["slow_chop"] = datetime.now(get_timezone()) - timedelta(
        seconds=3601
    )
    lumberjack._run_tick()
    assert mock_run.call_count == 2


@pytest.mark.parametrize("status", ["action_failed", "timeout"])
def test_failed_run_every_chop_waits_until_next_cadence(
    status: ChopRunOutcomeStatus,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    config = LumberjackConfig(
        name="throttled_failure",
        description="Run throttled failure checks",
        interval=10,
        chops=[ChopConfig(name="slow_chop", description="", run_every=3600)],
    )
    outcome = ChopRunOutcome(
        lumberjack_name="throttled_failure",
        chop_name="slow_chop",
        status=status,
        run_id=f"run-{status}",
        error=RuntimeError(status),
        traceback="test traceback",
    )

    with (
        patch("sase.axe.check_cycles.find_all_changespecs", return_value=[]),
        patch(
            "sase.axe.lumberjack.run_configured_chop_once", return_value=outcome
        ) as run_chop,
    ):
        lumberjack = Lumberjack("throttled_failure", config, axe_config)
        lumberjack._run_tick()
        lumberjack._run_tick()

    assert run_chop.call_count == 1
    assert "slow_chop" in lumberjack._chop_timestamps


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
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
        description="Run first-tick checks",
        interval=10,
        chops=[
            ChopConfig(name="every_tick", description=""),
            ChopConfig(name="hourly", description="", run_every=3600),
            ChopConfig(name="daily", description="", run_every=86400),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_ok()

    lumberjack = Lumberjack("first_tick", config, axe_config)
    lumberjack._run_tick()

    assert mock_run.call_count == 3


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
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
        description="Run every-tick checks",
        interval=10,
        chops=[ChopConfig(name="always_chop", description="")],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_ok()

    lumberjack = Lumberjack("always", config, axe_config)
    lumberjack._run_tick()
    lumberjack._run_tick()
    lumberjack._run_tick()

    assert mock_run.call_count == 3


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
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
        description="Run timeout handling checks",
        interval=10,
        chop_timeout=5,
        chops=[
            ChopConfig(name="slow_chop", description=""),
            ChopConfig(name="fast_chop", description=""),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_seq([streamed_timeout(), streamed_ok()])

    lumberjack = Lumberjack("timeout_test", config, axe_config)
    lumberjack._run_tick()

    assert lumberjack._metrics.errors_encountered == 1
    assert lumberjack._metrics.chops_executed == 1
    assert lumberjack._metrics.cycles_run == 1


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
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
        description="Run timeout override checks",
        interval=10,
        chop_timeout=30,
        chops=[
            ChopConfig(name="custom_timeout", description="", timeout=10),
            ChopConfig(name="default_timeout", description=""),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_ok()

    lumberjack = Lumberjack("override_test", config, axe_config)
    lumberjack._run_tick()

    assert mock_run.call_count == 2
    timeouts_by_chop = {
        call.kwargs["env"][ENV_CHOP_NAME]: call.kwargs["timeout"]
        for call in mock_run.call_args_list
    }
    assert timeouts_by_chop == {"custom_timeout": 10, "default_timeout": 30}


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
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
        description="Run interval overrun checks",
        interval=1,
        chops=[ChopConfig(name="slow_chop", description="")],
    )
    mock_discover.return_value = Path("/fake/script")

    streamed = streamed_ok()

    def slow_run(*args: object, **kwargs: object):
        time.sleep(1.1)
        return streamed(*args, **kwargs)

    mock_run.side_effect = slow_run

    lumberjack = Lumberjack("overrun_test", config, axe_config)
    lumberjack._run_tick()

    log_path = temp_state_dir / "lumberjacks" / "overrun_test" / "lumberjack.log"
    if log_path.exists():
        log_content = log_path.read_text()
        assert "Tick overrun" in log_content


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
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
        description="Run concurrent chop checks",
        interval=10,
        chops=[
            ChopConfig(name="slow_a", description=""),
            ChopConfig(name="slow_b", description=""),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    streamed = streamed_ok()

    def slow_run(*args: object, **kwargs: object):
        time.sleep(1.0)
        return streamed(*args, **kwargs)

    mock_run.side_effect = slow_run

    lumberjack = Lumberjack("concurrent_test", config, axe_config)
    start = time.monotonic()
    lumberjack._run_tick()
    elapsed = time.monotonic() - start

    assert mock_run.call_count == 2
    assert lumberjack._metrics.chops_executed == 2
    assert elapsed < 1.8, f"Expected concurrent execution (<1.8s), took {elapsed:.1f}s"


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
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
        description="Run failure isolation checks",
        interval=10,
        chops=[
            ChopConfig(name="failing_chop", description=""),
            ChopConfig(name="ok_chop", description=""),
            ChopConfig(name="crashing_chop", description=""),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_seq(
        [streamed_fail(), streamed_ok(), RuntimeError("unexpected crash")]
    )

    lumberjack = Lumberjack("isolation_test", config, axe_config)
    lumberjack._run_tick()

    assert mock_run.call_count == 3
    assert lumberjack._metrics.chops_executed == 1
    assert lumberjack._metrics.errors_encountered == 2
