"""Tests for Lumberjack chop run history."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.lumberjack import Lumberjack
from sase.axe.state import (
    read_chop_run,
    read_chop_run_index,
    read_chop_run_log_tail,
)
from tests._axe_lumberjack_fixtures import (
    single_chop_run_id,
    streamed_fail,
    streamed_ok,
    streamed_seq,
    streamed_timeout,
)

pytest_plugins = ("tests._axe_lumberjack_fixtures",)


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_successful_chop_records_run_history(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    lumberjack_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """A successful chop run produces a status=success entry with exit_code 0."""
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_ok(output="hello\n")

    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._run_tick()

    run_id = single_chop_run_id("test_lumberjack", "hook_checks")
    entry = read_chop_run("test_lumberjack", "hook_checks", run_id)
    assert entry is not None
    assert entry.status == "success"
    assert entry.exit_code == 0
    assert entry.error is None
    assert entry.lumberjack_name == "test_lumberjack"
    assert entry.chop_name == "hook_checks"
    log_tail = read_chop_run_log_tail("test_lumberjack", "hook_checks", run_id)
    assert "hello" in log_tail


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_failed_chop_records_failure_history(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    lumberjack_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """A failing chop run produces a status=failure entry with the exit code."""
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_fail(code=2, output="boom")

    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._run_tick()

    run_id = single_chop_run_id("test_lumberjack", "hook_checks")
    entry = read_chop_run("test_lumberjack", "hook_checks", run_id)
    assert entry is not None
    assert entry.status == "failure"
    assert entry.exit_code == 2
    assert entry.error is not None and "exit code 2" in entry.error
    log_tail = read_chop_run_log_tail("test_lumberjack", "hook_checks", run_id)
    assert "boom" in log_tail


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_timed_out_chop_records_timeout_history(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    lumberjack_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """A chop that times out produces a status=timeout entry."""
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_timeout()

    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._run_tick()

    run_id = single_chop_run_id("test_lumberjack", "hook_checks")
    entry = read_chop_run("test_lumberjack", "hook_checks", run_id)
    assert entry is not None
    assert entry.status == "timeout"
    assert entry.exit_code is None
    assert entry.error is not None and "timed out" in entry.error


@patch("sase.axe.chop_runner.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_missing_script_records_missing_script_history(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    temp_state_dir: Path,
    lumberjack_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """An unresolved chop script produces a status=missing_script entry."""
    mock_discover.return_value = None

    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._run_tick()

    run_id = single_chop_run_id("test_lumberjack", "hook_checks")
    entry = read_chop_run("test_lumberjack", "hook_checks", run_id)
    assert entry is not None
    assert entry.status == "missing_script"
    assert entry.exit_code is None
    assert entry.error is not None
    assert "not found" in entry.error


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_every_skip_does_not_record_history(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """run_every-throttled chops do not pollute the history with skip entries."""
    config = LumberjackConfig(
        name="throttled",
        description="Run throttled history checks",
        interval=10,
        chops=[ChopConfig(name="slow_chop", description="", run_every=3600)],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_ok()

    lumberjack = Lumberjack("throttled", config, axe_config)
    lumberjack._run_tick()
    lumberjack._run_tick()

    assert mock_run.call_count == 1
    index = read_chop_run_index("throttled", "slow_chop")
    assert len(index) == 1


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_chop_history_is_pruned_to_max(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    lumberjack_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """A chop with 12 attempts leaves exactly 10 readable newest entries."""
    from sase.axe.state import MAX_CHOP_RUN_HISTORY

    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_ok()

    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    for _ in range(MAX_CHOP_RUN_HISTORY + 2):
        lumberjack._run_tick()
        time.sleep(0.001)

    index = read_chop_run_index("test_lumberjack", "hook_checks")
    assert len(index) == MAX_CHOP_RUN_HISTORY
    for run_id in index:
        assert read_chop_run("test_lumberjack", "hook_checks", run_id) is not None
