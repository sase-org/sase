"""Tests for per-lumberjack state management in the axe state module."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.state import (
    MAX_CHOP_RUN_HISTORY,
    ChopRunEntry,
    LumberjackMetrics,
    LumberjackStatus,
    chop_index_path,
    chop_run_log_path,
    chop_run_meta_path,
    chop_runs_dir,
    ensure_chop_dirs,
    ensure_lumberjack_dirs,
    generate_chop_run_id,
    list_lumberjack_names,
    lumberjack_log_path,
    read_chop_run,
    read_chop_run_index,
    read_chop_run_log_tail,
    read_lumberjack_log_tail,
    read_lumberjack_metrics,
    read_lumberjack_pid,
    read_lumberjack_status,
    remove_lumberjack_pid,
    write_chop_run,
    write_lumberjack_pid,
)


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Create a temporary state directory for testing."""
    state_dir = tmp_path / ".sase" / "axe"
    lumberjack_dir = state_dir / "lumberjacks"
    shared_dir = state_dir / "shared"
    with (
        patch("sase.axe.state.AXE_STATE_DIR", state_dir),
        patch("sase.axe.state.JACK_STATE_DIR", lumberjack_dir),
        patch("sase.axe.state.SHARED_STATE_DIR", shared_dir),
    ):
        yield state_dir


# --- Directory Creation ---


# --- PID File ---


def test_remove_lumberjack_pid(temp_state_dir: Path) -> None:
    """Test removing a lumberjack PID file."""
    write_lumberjack_pid("hooks")
    assert read_lumberjack_pid("hooks") is not None
    remove_lumberjack_pid("hooks")
    assert read_lumberjack_pid("hooks") is None


def test_remove_lumberjack_pid_no_error_when_missing(
    temp_state_dir: Path,
) -> None:
    """Test that removing a non-existent PID file doesn't error."""
    remove_lumberjack_pid("hooks")  # Should not raise


# --- Status ---


def test_read_lumberjack_status_returns_none_when_missing(
    temp_state_dir: Path,
) -> None:
    """Test that read_lumberjack_status returns None when no file."""
    assert read_lumberjack_status("hooks") is None


def test_lumberjack_status_defaults() -> None:
    """Test LumberjackStatus default field values."""
    status = LumberjackStatus(
        name="test",
        pid=1,
        started_at="now",
        status="running",
        interval=1,
    )
    assert status.chops == []
    assert status.last_cycle is None
    assert status.cycles_run == 0
    assert status.errors_encountered == 0
    assert status.uptime_seconds == 0


# --- Metrics ---


def test_read_lumberjack_metrics_returns_none_when_missing(
    temp_state_dir: Path,
) -> None:
    """Test that read_lumberjack_metrics returns None when no file."""
    assert read_lumberjack_metrics("hooks") is None


def test_lumberjack_metrics_defaults() -> None:
    """Test LumberjackMetrics default values."""
    metrics = LumberjackMetrics()
    assert metrics.cycles_run == 0
    assert metrics.chops_executed == 0
    assert metrics.total_updates == 0
    assert metrics.errors_encountered == 0


# --- Log Paths ---


def test_read_lumberjack_log_tail_returns_content(
    temp_state_dir: Path,
) -> None:
    """Test reading lumberjack log tail."""
    ensure_lumberjack_dirs("hooks")
    log_path = lumberjack_log_path("hooks")
    log_path.write_text("line1\nline2\nline3\n")

    result = read_lumberjack_log_tail("hooks", lines=2)
    assert "line2" in result
    assert "line3" in result


def test_read_lumberjack_log_tail_returns_empty_when_missing(
    temp_state_dir: Path,
) -> None:
    """Test that read_lumberjack_log_tail returns empty for missing log."""
    assert read_lumberjack_log_tail("hooks") == ""


# --- Listing ---


def test_list_lumberjack_names_empty(temp_state_dir: Path) -> None:
    """Test listing lumberjack names when none exist."""
    assert list_lumberjack_names() == []


def test_list_lumberjack_names(temp_state_dir: Path) -> None:
    """Test listing lumberjack names after creating some."""
    ensure_lumberjack_dirs("hooks")
    ensure_lumberjack_dirs("checks")
    ensure_lumberjack_dirs("comments")

    names = list_lumberjack_names()
    assert names == ["checks", "comments", "hooks"]


# --- Chop Run History ---


def _make_entry(
    lumberjack: str = "hooks",
    chop: str = "hook_checks",
    run_id: str | None = None,
    status: str = "success",
    exit_code: int | None = 0,
    duration_ms: int = 12,
) -> ChopRunEntry:
    rid = run_id or generate_chop_run_id()
    return ChopRunEntry(
        run_id=rid,
        lumberjack_name=lumberjack,
        chop_name=chop,
        started_at="2026-05-11T20:00:00+00:00",
        finished_at="2026-05-11T20:00:00.012000+00:00",
        duration_ms=duration_ms,
        status=status,  # type: ignore[arg-type]
        exit_code=exit_code,
    )


def test_ensure_chop_dirs_creates_runs_subdir(temp_state_dir: Path) -> None:
    """ensure_chop_dirs creates the per-chop runs directory lazily."""
    chop_dir = ensure_chop_dirs("hooks", "hook_checks")
    assert chop_dir.exists()
    assert (chop_dir / "runs").is_dir()
    assert chop_runs_dir("hooks", "hook_checks") == chop_dir / "runs"


def test_ensure_lumberjack_dirs_does_not_create_chops_dir(
    temp_state_dir: Path,
) -> None:
    """The lumberjack-level helper does not eagerly create per-chop dirs."""
    lumberjack_dir = ensure_lumberjack_dirs("hooks")
    assert lumberjack_dir.exists()
    assert not (lumberjack_dir / "chops").exists()


def test_write_chop_run_round_trips_metadata_and_log(
    temp_state_dir: Path,
) -> None:
    """A written entry can be read back with the same metadata and log."""
    entry = _make_entry(run_id="20260511T200000_000001")
    write_chop_run(entry, output="hello\nworld\n")

    index = read_chop_run_index("hooks", "hook_checks")
    assert index == ["20260511T200000_000001"]

    loaded = read_chop_run("hooks", "hook_checks", "20260511T200000_000001")
    assert loaded is not None
    assert loaded.status == "success"
    assert loaded.exit_code == 0
    assert loaded.output_bytes == len(b"hello\nworld\n")
    assert loaded.output_log == "20260511T200000_000001.log"

    tail = read_chop_run_log_tail("hooks", "hook_checks", "20260511T200000_000001")
    assert tail == "hello\nworld\n"


def test_write_chop_run_orders_newest_first(temp_state_dir: Path) -> None:
    """Index returns most recently written runs first."""
    for i in range(3):
        write_chop_run(
            _make_entry(run_id=f"20260511T200000_00000{i}"),
            output=f"run {i}\n",
        )

    assert read_chop_run_index("hooks", "hook_checks") == [
        "20260511T200000_000002",
        "20260511T200000_000001",
        "20260511T200000_000000",
    ]


def test_write_chop_run_prunes_beyond_max(temp_state_dir: Path) -> None:
    """Recording more than MAX runs prunes old metadata and log files."""
    for i in range(MAX_CHOP_RUN_HISTORY + 2):
        write_chop_run(
            _make_entry(run_id=f"20260511T200000_{i:06d}"),
            output=f"run {i}\n",
        )

    index = read_chop_run_index("hooks", "hook_checks")
    assert len(index) == MAX_CHOP_RUN_HISTORY
    # Newest two retained ids are 11 and 10; oldest pruned are 00 and 01.
    assert index[0] == "20260511T200000_000011"
    assert index[-1] == "20260511T200000_000002"

    pruned_meta = chop_run_meta_path("hooks", "hook_checks", "20260511T200000_000000")
    pruned_log = chop_run_log_path("hooks", "hook_checks", "20260511T200000_000000")
    assert not pruned_meta.exists()
    assert not pruned_log.exists()


def test_read_chop_run_index_returns_empty_when_missing(
    temp_state_dir: Path,
) -> None:
    assert read_chop_run_index("hooks", "hook_checks") == []


def test_read_chop_run_returns_none_when_missing(temp_state_dir: Path) -> None:
    assert read_chop_run("hooks", "hook_checks", "nope") is None


def test_read_chop_run_returns_none_on_invalid_json(
    temp_state_dir: Path,
) -> None:
    """Malformed metadata files do not crash reads — they return None."""
    ensure_chop_dirs("hooks", "hook_checks")
    meta = chop_run_meta_path("hooks", "hook_checks", "bad")
    meta.write_text("{not json")
    assert read_chop_run("hooks", "hook_checks", "bad") is None


def test_read_chop_run_index_returns_empty_on_invalid_json(
    temp_state_dir: Path,
) -> None:
    ensure_chop_dirs("hooks", "hook_checks")
    chop_index_path("hooks", "hook_checks").write_text("{not json")
    assert read_chop_run_index("hooks", "hook_checks") == []


def test_read_chop_run_log_tail_returns_empty_for_missing_log(
    temp_state_dir: Path,
) -> None:
    assert read_chop_run_log_tail("hooks", "hook_checks", "missing") == ""


def test_read_chop_run_log_tail_bounded(temp_state_dir: Path) -> None:
    """Tail respects the requested line count rather than reading the full log."""
    entry = _make_entry(run_id="20260511T200000_000001")
    body = "".join(f"line {i}\n" for i in range(200))
    write_chop_run(entry, output=body)

    tail = read_chop_run_log_tail(
        "hooks", "hook_checks", "20260511T200000_000001", lines=5
    )
    assert tail.count("\n") == 5
    assert "line 199" in tail
    assert "line 0\n" not in tail


def test_generate_chop_run_id_sortable(temp_state_dir: Path) -> None:
    """Run ids generated from increasing timestamps sort lexicographically."""
    from datetime import datetime, timedelta

    from sase.core.time import get_timezone

    base = datetime(2026, 5, 11, 12, 0, 0, tzinfo=get_timezone())
    ids = [generate_chop_run_id(base + timedelta(microseconds=i)) for i in range(3)]
    assert ids == sorted(ids)
