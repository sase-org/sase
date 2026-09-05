"""Tests for per-lumberjack state management in the axe state module."""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.state import (
    DEFAULT_LUMBERJACK_LOG_MAX_BYTES,
    MAX_CHOP_RUN_HISTORY,
    ChopRunEntry,
    LumberjackMetrics,
    LumberjackStatus,
    append_bounded_log,
    append_lumberjack_log,
    append_chop_run_output,
    chop_index_path,
    chop_run_log_path,
    chop_run_meta_path,
    chop_runs_dir,
    ensure_chop_dirs,
    ensure_lumberjack_dirs,
    finish_chop_run,
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
    reap_stale_log_rotation_temps,
    remove_lumberjack_pid,
    start_chop_run,
    update_chop_run_pid,
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
        patch("sase.axe.state.axe_state_dir", return_value=state_dir),
        patch("sase.axe.state.jack_state_dir", return_value=lumberjack_dir),
        patch("sase.axe.state.shared_state_dir", return_value=shared_dir),
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
    assert metrics.chops_spawned == 0
    assert metrics.chops_no_op == 0
    assert metrics.chops_skipped == {}
    assert metrics.last_tick_spawns == 0
    assert metrics.spawn_rate_per_minute == 0.0
    assert metrics.no_op_ratio == 0.0


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


def test_append_lumberjack_log_caps_existing_large_file(
    temp_state_dir: Path,
) -> None:
    """Bounded appends keep only recent bytes from oversized aggregate logs."""
    ensure_lumberjack_dirs("hooks")
    log_path = lumberjack_log_path("hooks")
    log_path.write_bytes(b"old\n" * 100)

    append_lumberjack_log("hooks", "newest\n", max_bytes=96)

    data = log_path.read_bytes()
    assert len(data) <= 96
    assert b"newest\n" in data
    assert b"truncated" in data


def test_append_bounded_log_rotation_leaves_half_cap_headroom(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "lumberjack-hooks.log"
    log_path.write_bytes(b"old\n" * 100)

    append_bounded_log(log_path, b"newest\n", max_bytes=256)

    data = log_path.read_bytes()
    assert len(data) <= 128
    assert b"newest\n" in data
    assert b"truncated" in data


def test_append_bounded_log_below_cap_does_not_replace(tmp_path: Path) -> None:
    log_path = tmp_path / "lumberjack-hooks.log"
    log_path.write_bytes(b"existing\n")

    with patch("sase.axe._state_lumberjack._atomic_replace_bytes") as replace:
        append_bounded_log(log_path, b"appended\n", max_bytes=256)

    replace.assert_not_called()
    assert log_path.read_bytes() == b"existing\nappended\n"


def test_log_rotation_reaps_only_stale_sibling_temps(tmp_path: Path) -> None:
    log_path = tmp_path / "lumberjack-hooks.log"
    log_path.write_bytes(b"old\n" * 100)
    stale = tmp_path / ".lumberjack-hooks.log.stale.tmp"
    recent = tmp_path / ".lumberjack-hooks.log.recent.tmp"
    unrelated = tmp_path / ".registry.json.stale.tmp"
    stale.write_bytes(b"stale")
    recent.write_bytes(b"recent")
    unrelated.write_bytes(b"unrelated")
    os.utime(stale, (1, 1))
    os.utime(unrelated, (1, 1))

    append_bounded_log(
        log_path,
        b"newest\n",
        max_bytes=256,
        temp_max_age_seconds=300,
    )

    assert not stale.exists()
    assert recent.exists()
    assert unrelated.exists()


def test_reap_stale_log_rotation_temps_recurses(tmp_path: Path) -> None:
    nested = tmp_path / "lumberjacks" / "hooks" / "logs"
    nested.mkdir(parents=True)
    aggregate = tmp_path / ".lumberjack-hooks.log.stale.tmp"
    per_jack = nested / ".output.log.stale.tmp"
    recent = nested / ".output.log.recent.tmp"
    for candidate in (aggregate, per_jack, recent):
        candidate.write_bytes(b"temp")
    os.utime(aggregate, (1, 1))
    os.utime(per_jack, (1, 1))

    reaped = reap_stale_log_rotation_temps(tmp_path, max_age_seconds=300)

    assert reaped == 2
    assert not aggregate.exists()
    assert not per_jack.exists()
    assert recent.exists()


def test_default_lumberjack_log_cap_is_50_mib() -> None:
    assert DEFAULT_LUMBERJACK_LOG_MAX_BYTES == 50 * 1024 * 1024


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
    finished_at: str | None = "2026-05-11T20:00:00.012000+00:00",
) -> ChopRunEntry:
    rid = run_id or generate_chop_run_id()
    return ChopRunEntry(
        run_id=rid,
        lumberjack_name=lumberjack,
        chop_name=chop,
        started_at="2026-05-11T20:00:00+00:00",
        finished_at=finished_at,
        duration_ms=duration_ms,
        status=status,  # type: ignore[arg-type]
        exit_code=exit_code,
    )


def _make_running_entry(
    lumberjack: str = "hooks",
    chop: str = "hook_checks",
    run_id: str | None = None,
    pid: int | None = None,
) -> ChopRunEntry:
    rid = run_id or generate_chop_run_id()
    return ChopRunEntry(
        run_id=rid,
        lumberjack_name=lumberjack,
        chop_name=chop,
        started_at="2026-05-11T20:00:00+00:00",
        finished_at=None,
        duration_ms=0,
        status="running",
        exit_code=None,
        pid=pid,
        source="scheduled",
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


def test_read_chop_run_tolerates_unknown_keys(temp_state_dir: Path) -> None:
    """An unknown key from a newer sase does not drop the run from history."""
    entry = _make_entry(run_id="20260511T200000_000001")
    write_chop_run(entry, output="hello\n")

    meta = chop_run_meta_path("hooks", "hook_checks", "20260511T200000_000001")
    data = json.loads(meta.read_text())
    data["a_future_field_this_reader_does_not_know_about"] = "surprise"
    meta.write_text(json.dumps(data))

    loaded = read_chop_run("hooks", "hook_checks", "20260511T200000_000001")
    assert loaded is not None
    assert loaded.status == "success"


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


# --- Streaming Run Helpers ---


def test_start_chop_run_creates_running_metadata_and_log(
    temp_state_dir: Path,
) -> None:
    """``start_chop_run`` opens an empty log + ``running`` metadata + index entry."""
    entry = _make_running_entry(run_id="20260511T200000_000001")
    log_path = start_chop_run(entry)

    assert log_path.exists()
    assert log_path.read_bytes() == b""

    loaded = read_chop_run("hooks", "hook_checks", "20260511T200000_000001")
    assert loaded is not None
    assert loaded.status == "running"
    assert loaded.finished_at is None
    assert loaded.duration_ms == 0
    assert loaded.output_log == "20260511T200000_000001.log"

    assert read_chop_run_index("hooks", "hook_checks") == [
        "20260511T200000_000001",
    ]


def test_append_chop_run_output_grows_log(temp_state_dir: Path) -> None:
    """``append_chop_run_output`` accumulates bytes into the run log."""
    entry = _make_running_entry(run_id="20260511T200000_000001")
    start_chop_run(entry)

    written = append_chop_run_output(
        "hooks", "hook_checks", "20260511T200000_000001", "first\n"
    )
    assert written == len(b"first\n")
    append_chop_run_output(
        "hooks", "hook_checks", "20260511T200000_000001", b"second\n"
    )

    tail = read_chop_run_log_tail("hooks", "hook_checks", "20260511T200000_000001")
    assert tail == "first\nsecond\n"


def test_append_chop_run_output_returns_zero_when_missing(
    temp_state_dir: Path,
) -> None:
    """Appending to a non-existent run is a no-op rather than an error."""
    assert append_chop_run_output("hooks", "hook_checks", "missing", "data") == 0


def test_update_chop_run_pid_patches_metadata(temp_state_dir: Path) -> None:
    """``update_chop_run_pid`` mutates only the pid field, leaving status intact."""
    entry = _make_running_entry(run_id="20260511T200000_000001")
    start_chop_run(entry)
    update_chop_run_pid("hooks", "hook_checks", "20260511T200000_000001", 99999)

    loaded = read_chop_run("hooks", "hook_checks", "20260511T200000_000001")
    assert loaded is not None
    assert loaded.pid == 99999
    assert loaded.status == "running"


def test_finish_chop_run_replaces_running_with_terminal(
    temp_state_dir: Path,
) -> None:
    """Finalizing updates the same run id with terminal status and exit code."""
    entry = _make_running_entry(run_id="20260511T200000_000001")
    start_chop_run(entry)
    append_chop_run_output("hooks", "hook_checks", "20260511T200000_000001", "hello\n")

    finish_chop_run(
        "hooks",
        "hook_checks",
        "20260511T200000_000001",
        status="success",
        finished_at="2026-05-11T20:00:01+00:00",
        duration_ms=1000,
        exit_code=0,
    )

    loaded = read_chop_run("hooks", "hook_checks", "20260511T200000_000001")
    assert loaded is not None
    assert loaded.status == "success"
    assert loaded.finished_at == "2026-05-11T20:00:01+00:00"
    assert loaded.exit_code == 0
    assert loaded.output_bytes == len(b"hello\n")

    # The index still has exactly one entry — no duplicate row appears.
    assert read_chop_run_index("hooks", "hook_checks") == [
        "20260511T200000_000001",
    ]


def test_finish_chop_run_does_not_prune_active_runs(temp_state_dir: Path) -> None:
    """A still-``running`` entry survives pruning even past MAX_CHOP_RUN_HISTORY."""
    active_id = "20260511T200000_999999"
    start_chop_run(_make_running_entry(run_id=active_id))

    # Add MAX terminal entries (newer-first by run_id lexicographic order).
    for i in range(MAX_CHOP_RUN_HISTORY):
        terminal_id = f"20260511T200001_{i:06d}"
        write_chop_run(_make_entry(run_id=terminal_id), output=f"terminal {i}\n")

    # Finish one more — pushing total terminal count to MAX + 1; one must
    # be pruned, but never the active entry.
    extra_id = "20260511T200002_000001"
    start_chop_run(_make_running_entry(run_id=extra_id))
    finish_chop_run(
        "hooks",
        "hook_checks",
        extra_id,
        status="success",
        finished_at="2026-05-11T20:00:02+00:00",
        duration_ms=5,
        exit_code=0,
    )

    index = read_chop_run_index("hooks", "hook_checks")
    assert active_id in index, "active running entry was pruned"
    terminal_kept = [rid for rid in index if rid != active_id]
    assert len(terminal_kept) == MAX_CHOP_RUN_HISTORY


def test_finish_chop_run_is_noop_for_missing_run(temp_state_dir: Path) -> None:
    """Finalizing a non-existent run id silently does nothing."""
    finish_chop_run(
        "hooks",
        "hook_checks",
        "unknown",
        status="success",
        finished_at="2026-05-11T20:00:01+00:00",
        duration_ms=1,
        exit_code=0,
    )
    assert read_chop_run("hooks", "hook_checks", "unknown") is None


def test_read_chop_run_log_tail_during_active_run(temp_state_dir: Path) -> None:
    """Tail reads pick up bytes appended while the entry is still ``running``."""
    entry = _make_running_entry(run_id="20260511T200000_000001")
    start_chop_run(entry)
    append_chop_run_output(
        "hooks", "hook_checks", "20260511T200000_000001", "partial\n"
    )

    tail = read_chop_run_log_tail(
        "hooks", "hook_checks", "20260511T200000_000001", lines=5
    )
    assert tail == "partial\n"


def test_running_entry_has_nullable_finished_at(temp_state_dir: Path) -> None:
    """The ``finished_at`` field is ``None`` for entries in ``running`` state."""
    entry = _make_running_entry(run_id="20260511T200000_000001")
    start_chop_run(entry)
    loaded = read_chop_run("hooks", "hook_checks", "20260511T200000_000001")
    assert loaded is not None
    assert loaded.finished_at is None
