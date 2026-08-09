"""Tests for Lumberjack streaming chop runs."""

import stat
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.lumberjack import Lumberjack
from sase.axe.state import read_chop_run, read_chop_run_index, read_chop_run_log_tail
from tests._axe_lumberjack_fixtures import streamed_ok

pytest_plugins = ("tests._axe_lumberjack_fixtures",)


def _make_streaming_script(tmp: Path, name: str, body: str) -> Path:
    """Drop an executable shell script under tmp/scripts/<name>."""
    scripts = tmp / "scripts"
    scripts.mkdir(exist_ok=True)
    script = scripts / name
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


@patch("sase.axe.check_cycles.find_all_patches", return_value=[])
def test_streaming_chop_writes_output_before_exit(
    mock_find: MagicMock,
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    """A long-running script chop appears in the run log before its subprocess exits."""
    import threading

    _make_streaming_script(
        tmp_path,
        "live_chop",
        "echo first\nsleep 0.6\necho second\n",
    )
    axe_config = AxeConfig(
        max_hook_runners=3,
        max_agent_runners=3,
        zombie_timeout_seconds=3600,
        query="",
        chop_script_dirs=[str(tmp_path / "scripts")],
    )
    config = LumberjackConfig(
        name="live",
        description="Run live streaming checks",
        interval=10,
        chops=[ChopConfig(name="live_chop", description="")],
    )

    lumberjack = Lumberjack("live", config, axe_config)

    worker = threading.Thread(target=lumberjack._run_tick, daemon=True)
    worker.start()

    mid_run_tail: str | None = None
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        index = read_chop_run_index("live", "live_chop")
        if index:
            run_id = index[0]
            entry = read_chop_run("live", "live_chop", run_id)
            tail = read_chop_run_log_tail("live", "live_chop", run_id)
            if (
                entry is not None
                and entry.status == "running"
                and "first" in tail
                and "second" not in tail
            ):
                mid_run_tail = tail
                break
        time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))

    worker.join(timeout=5.0)
    assert not worker.is_alive(), "lumberjack tick failed to finish"

    index = read_chop_run_index("live", "live_chop")
    assert len(index) == 1
    run_id = index[0]
    entry = read_chop_run("live", "live_chop", run_id)
    assert entry is not None
    assert entry.status == "success"
    assert entry.finished_at is not None
    assert entry.exit_code == 0
    final_tail = read_chop_run_log_tail("live", "live_chop", run_id)
    assert "first" in final_tail
    assert "second" in final_tail
    assert mid_run_tail is not None, (
        "expected first line in log while entry was still ``running``"
    )


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_patches", return_value=[])
def test_streaming_chop_records_pid_on_running_entry(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    lumberjack_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """When the runner reports a pid, the running entry stores it before finalizing."""
    mock_discover.return_value = Path("/fake/script")
    seen_pids: dict[str, int | None] = {"during_run": None}
    streamed = streamed_ok(pid=54321)

    def _side_effect(*args: object, **kwargs: object):
        result = streamed(*args, **kwargs)
        index = read_chop_run_index("test_lumberjack", "hook_checks")
        if index:
            entry = read_chop_run("test_lumberjack", "hook_checks", index[0])
            if entry is not None:
                seen_pids["during_run"] = entry.pid
        return result

    mock_run.side_effect = _side_effect

    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._run_tick()

    assert seen_pids["during_run"] == 54321
    run_id = read_chop_run_index("test_lumberjack", "hook_checks")[0]
    entry = read_chop_run("test_lumberjack", "hook_checks", run_id)
    assert entry is not None
    assert entry.pid == 54321
    assert entry.status == "success"


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_patches", return_value=[])
def test_streaming_chop_records_source_scheduled(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    lumberjack_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """Scheduled runs persist ``source='scheduled'`` so manual runs can be distinguished."""
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_ok()

    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._run_tick()

    run_id = read_chop_run_index("test_lumberjack", "hook_checks")[0]
    entry = read_chop_run("test_lumberjack", "hook_checks", run_id)
    assert entry is not None
    assert entry.source == "scheduled"
