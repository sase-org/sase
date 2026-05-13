"""Tests for Lumberjack lifecycle and status updates."""

import os
from pathlib import Path

from sase.axe.config import AxeConfig, LumberjackConfig
from sase.axe.lumberjack import Lumberjack

pytest_plugins = ("tests._axe_lumberjack_fixtures",)


def test_lumberjack_with_query(
    temp_state_dir: Path, lumberjack_config: LumberjackConfig
) -> None:
    """Test that Lumberjack accepts a parseable query and forwards it to the check runner."""
    config = AxeConfig(query='"test"')
    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, config)
    assert lumberjack._check_runner.query == '"test"'


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


def test_handle_shutdown_sets_running_false(
    temp_state_dir: Path, lumberjack_config: LumberjackConfig, axe_config: AxeConfig
) -> None:
    """Test that SIGTERM handler sets _running to False."""
    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    assert lumberjack._running is True
    lumberjack._handle_shutdown(15, None)
    assert lumberjack._running is False


def test_log_flush_respects_axe_log_cap(
    temp_state_dir: Path,
    lumberjack_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """Repeated aggregate logs cannot grow beyond configured cap."""
    axe_config.lumberjack_log_max_bytes = 256
    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)

    for i in range(30):
        lumberjack._log(f"line {i} " + ("x" * 40))

    log_path = (
        temp_state_dir / "lumberjacks" / "test_lumberjack" / "logs" / "output.log"
    )
    data = log_path.read_text()
    assert log_path.stat().st_size <= 256
    assert "29" in data
