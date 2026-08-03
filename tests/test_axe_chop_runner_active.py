"""Tests for active chop run detection and stale run cleanup."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from sase.axe.chop_runner import _active_script_chop_run
from sase.axe.chop_runner_script_dedupe import _script_chop_run_age_seconds
from sase.axe.state import ChopRunEntry, read_chop_run, start_chop_run

from tests.axe_chop_runner_helpers import started_at_seconds_ago

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def test_active_script_chop_run_returns_none_when_no_history(
    temp_state_dir: Path,
) -> None:
    assert _active_script_chop_run("lj", "chop") is None


def test_active_script_chop_run_finds_running_entry(temp_state_dir: Path) -> None:
    entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="lj",
        chop_name="chop",
        started_at=started_at_seconds_ago(0),
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(entry)

    live = _active_script_chop_run("lj", "chop")
    assert live is not None
    assert live.run_id == entry.run_id


def test_active_script_chop_run_keeps_running_entry_with_live_pid(
    temp_state_dir: Path,
) -> None:
    started_at = datetime(2026, 1, 1, 12, 0, 0)
    entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="lj",
        chop_name="chop",
        started_at=started_at.isoformat(),
        finished_at=None,
        duration_ms=0,
        status="running",
        pid=12345,
    )
    start_chop_run(entry)

    with patch("sase.axe.chop_runner.is_process_running", return_value=True):
        live = _active_script_chop_run("lj", "chop")

    assert live is not None
    assert live.run_id == entry.run_id


def test_active_script_chop_run_finalizes_dead_pid_and_returns_none(
    temp_state_dir: Path,
) -> None:
    started_at = datetime(2026, 1, 1, 12, 0, 0)
    entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="lj",
        chop_name="chop",
        started_at=started_at.isoformat(),
        finished_at=None,
        duration_ms=0,
        status="running",
        pid=12345,
    )
    start_chop_run(entry)

    with patch("sase.axe.chop_runner.is_process_running", return_value=False):
        assert _active_script_chop_run("lj", "chop") is None

    finalized = read_chop_run("lj", "chop", entry.run_id)
    assert finalized is not None
    assert finalized.status == "failure"
    assert finalized.finished_at is not None
    assert finalized.error == "stale running chop process exited: pid 12345"


def test_active_script_chop_run_keeps_recent_pidless_running_entry(
    temp_state_dir: Path,
) -> None:
    entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="lj",
        chop_name="chop",
        started_at=started_at_seconds_ago(30),
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(entry)

    with patch("sase.axe.chop_runner.is_process_running") as mock_running:
        live = _active_script_chop_run("lj", "chop", pidless_stale_after_seconds=90)

    assert live is not None
    assert live.run_id == entry.run_id
    mock_running.assert_not_called()


def test_active_script_chop_run_finalizes_old_pidless_running_entry(
    temp_state_dir: Path,
) -> None:
    entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="lj",
        chop_name="chop",
        started_at=started_at_seconds_ago(120),
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(entry)

    with patch("sase.axe.chop_runner.is_process_running") as mock_running:
        live = _active_script_chop_run("lj", "chop", pidless_stale_after_seconds=90)

    assert live is None
    mock_running.assert_not_called()
    finalized = read_chop_run("lj", "chop", entry.run_id)
    assert finalized is not None
    assert finalized.status == "failure"
    assert finalized.finished_at is not None
    assert finalized.error == (
        "stale running chop never recorded a pid after 90s grace window"
    )


def test_pidless_age_uses_configured_timezone_for_naive_rows(
    tz_divergence: None,
) -> None:
    entry = ChopRunEntry(
        run_id="20260703T062449_000000",
        lumberjack_name="lj",
        chop_name="chop",
        started_at="2026-07-03T06:24:49",
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    now = datetime(2026, 7, 3, 10, 25, 49, tzinfo=UTC)

    assert _script_chop_run_age_seconds(entry, now) == 60


def test_active_script_chop_run_returns_none_when_newest_finalized(
    temp_state_dir: Path,
) -> None:
    """A finalized newest entry means no live run, even if older entries exist."""
    from sase.axe.state import finish_chop_run

    started_at = datetime(2026, 1, 1, 12, 0, 0)
    entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="lj",
        chop_name="chop",
        started_at=started_at.isoformat(),
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(entry)
    finish_chop_run(
        "lj",
        "chop",
        entry.run_id,
        status="success",
        finished_at=datetime(2026, 1, 1, 12, 0, 1).isoformat(),
        duration_ms=1000,
        exit_code=0,
    )

    assert _active_script_chop_run("lj", "chop") is None
