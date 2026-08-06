"""Unit tests for the selector's per-test-file cost model.

Nothing here runs a real test suite: the recorder is fed synthetic pytest
reports and the table is written by hand, so the assertions are about the model
— what it merges, what it refuses to estimate — rather than about how fast this
repository happens to be today.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests._test_selection import SelectionOptions, select_tests
from tests._test_selection_fixtures import (
    _touch,
    build_fixture_repo,
    install_fresh_baseline,
)
from tests._test_selection_timings import (
    DEFAULT_MIN_COVERAGE,
    KEEP_RECORDINGS,
    MIN_COVERAGE_ENV,
    REASON_EMPTY_SELECTION,
    REASON_ESCALATED,
    REASON_INSUFFICIENT_COVERAGE,
    REASON_NO_TABLE,
    TIMINGS_DIR_ENV,
    TIMINGS_DISABLED_ENV,
    TimingTable,
    estimate_serial_seconds,
    load_timing_table,
    min_coverage,
    prune_recordings,
    recording_paths,
    file_for_nodeid,
    timings_directory,
    timings_enabled,
    write_timings,
)
from tests._test_selection_timings_plugin import (
    TIMINGS_RECORD_ENV,
    FileDurationRecorder,
    _recorder_request,
)


def _write_recording(
    directory: Path,
    durations: dict[str, float],
    *,
    minute: int,
    mode: str = "fast",
    host: str | None = None,
) -> Path:
    """One recording at a fixed timestamp, so merge order is deterministic."""
    path = write_timings(
        directory,
        durations,
        mode=mode,
        host=host,
        pid=1000 + minute,
        now=datetime(2026, 8, 6, 12, minute, 0, tzinfo=UTC),
    )
    assert path is not None
    return path


@pytest.fixture
def timings_dir(tmp_path: Path) -> Path:
    return tmp_path / "store" / "timings"


@pytest.fixture(autouse=True)
def _neutral_timings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the host's own knobs out of this module's assertions."""
    for name in (TIMINGS_DIR_ENV, TIMINGS_DISABLED_ENV, MIN_COVERAGE_ENV):
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------
# Node IDs and locations
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("nodeid", "expected"),
    [
        ("tests/test_a.py::test_one", "tests/test_a.py"),
        ("tests/test_a.py::TestClass::test_one[param::weird]", "tests/test_a.py"),
        # A collection error names the file and nothing else.
        ("tests/test_a.py", "tests/test_a.py"),
        (r"tests\test_a.py::test_one", "tests/test_a.py"),
        ("", None),
        ("::test_one", None),
        ("tests/data/fixture.txt", None),
    ],
)
def test_file_for_nodeid_parses(nodeid: str, expected: str | None) -> None:
    assert file_for_nodeid(nodeid) == expected


def test_timings_directory_lives_inside_the_project_store(tmp_path: Path) -> None:
    store = tmp_path / "test-selection" / "gh_org__repo"
    assert timings_directory(store, {}) == store / "timings"


def test_timings_directory_honours_the_override(tmp_path: Path) -> None:
    override = tmp_path / "elsewhere"
    assert (
        timings_directory(tmp_path / "store", {TIMINGS_DIR_ENV: str(override)})
        == override
    )


def test_timings_enabled_reads_the_disable_switch() -> None:
    assert timings_enabled({}) is True
    assert timings_enabled({TIMINGS_DISABLED_ENV: "1"}) is False


# --------------------------------------------------------------------------
# Recording and pruning
# --------------------------------------------------------------------------


def test_write_timings_records_durations(timings_dir: Path) -> None:
    path = _write_recording(timings_dir, {"tests/test_a.py": 1.5}, minute=1)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert payload["durations"] == {"tests/test_a.py": 1.5}
    assert payload["mode"] == "fast"
    assert payload["file_count"] == 1


def test_write_timings_says_nothing_when_it_measured_nothing(
    timings_dir: Path,
) -> None:
    assert write_timings(timings_dir, {}, mode="fast") is None
    assert recording_paths(timings_dir) == []


def test_write_timings_prunes_to_the_newest_recordings(timings_dir: Path) -> None:
    for minute in range(KEEP_RECORDINGS + 3):
        _write_recording(timings_dir, {"tests/test_a.py": 1.0}, minute=minute)
    kept = recording_paths(timings_dir)
    assert len(kept) == KEEP_RECORDINGS
    # Oldest first, so the survivors are the tail of what was written.
    assert kept[0].name.startswith("20260806T1203")


def test_prune_recordings_leaves_unfamiliar_files_alone(timings_dir: Path) -> None:
    _write_recording(timings_dir, {"tests/test_a.py": 1.0}, minute=1)
    stranger = timings_dir / "notes.txt"
    stranger.write_text("not ours\n", encoding="utf-8")
    assert prune_recordings(timings_dir, keep=0) != []
    assert stranger.exists()


def test_recording_paths_tolerates_a_missing_directory(tmp_path: Path) -> None:
    assert recording_paths(tmp_path / "nope") == []


# --------------------------------------------------------------------------
# The merged table
# --------------------------------------------------------------------------


def test_load_timing_table_merges_newest_wins(timings_dir: Path) -> None:
    _write_recording(
        timings_dir, {"tests/test_a.py": 10.0, "tests/test_b.py": 2.0}, minute=1
    )
    _write_recording(timings_dir, {"tests/test_a.py": 4.0}, minute=2, mode="scoped")
    table = load_timing_table(timings_dir)
    # The scoped recording refreshed the file it covered and discarded nothing.
    assert table.durations == {"tests/test_a.py": 4.0, "tests/test_b.py": 2.0}
    assert table.total_seconds == pytest.approx(6.0)
    assert table.file_count == 2
    assert len(table.sources) == 2


def test_load_timing_table_skips_another_hosts_recording(timings_dir: Path) -> None:
    _write_recording(timings_dir, {"tests/test_a.py": 1.0}, minute=1)
    _write_recording(timings_dir, {"tests/test_b.py": 9.0}, minute=2, host="host-b")
    table = load_timing_table(timings_dir)
    assert table.durations == {"tests/test_a.py": 1.0}


def test_load_timing_table_ignores_unreadable_and_foreign_payloads(
    timings_dir: Path,
) -> None:
    _write_recording(timings_dir, {"tests/test_a.py": 1.0}, minute=1)
    (timings_dir / "20260806T120500-999.json").write_text("{", encoding="utf-8")
    (timings_dir / "20260806T120600-998.json").write_text(
        json.dumps({"schema": 99, "durations": {"tests/test_z.py": 5.0}}),
        encoding="utf-8",
    )
    table = load_timing_table(timings_dir)
    assert table.durations == {"tests/test_a.py": 1.0}


def test_table_identity_changes_when_a_recording_lands(timings_dir: Path) -> None:
    _write_recording(timings_dir, {"tests/test_a.py": 1.0}, minute=1)
    first = load_timing_table(timings_dir)
    _write_recording(timings_dir, {"tests/test_b.py": 1.0}, minute=2)
    second = load_timing_table(timings_dir)
    assert first.identity is not None
    assert second.identity != first.identity
    assert first.payload()["file_count"] == 1
    assert second.payload()["sources"] == list(second.sources)


def test_load_timing_table_on_an_empty_directory(tmp_path: Path) -> None:
    table = load_timing_table(tmp_path / "nope")
    assert table.empty
    assert table.identity is None
    assert table.payload()["recorded_at"] is None


# --------------------------------------------------------------------------
# Estimating
# --------------------------------------------------------------------------


def test_estimate_sums_the_known_files() -> None:
    table = TimingTable(durations={"tests/test_a.py": 3.0, "tests/test_b.py": 7.0})
    estimate = estimate_serial_seconds(
        ["tests/test_a.py", "tests/test_b.py"], table=table, environ={}
    )
    assert estimate.available
    assert estimate.seconds == pytest.approx(10.0)
    assert estimate.coverage == pytest.approx(1.0)
    assert estimate.missing_count == 0
    assert estimate.reason is None


def test_estimate_extrapolates_a_few_unknown_files_at_the_mean() -> None:
    table = TimingTable(durations={f"tests/test_{index}.py": 2.0 for index in range(9)})
    paths = [f"tests/test_{index}.py" for index in range(9)] + ["tests/test_new.py"]
    estimate = estimate_serial_seconds(paths, table=table, environ={})
    assert estimate.coverage == pytest.approx(0.9)
    assert estimate.seconds == pytest.approx(20.0)
    assert estimate.missing_count == 1


def test_estimate_refuses_a_mostly_unknown_selection() -> None:
    table = TimingTable(durations={"tests/test_a.py": 3.0})
    estimate = estimate_serial_seconds(
        ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"],
        table=table,
        environ={},
    )
    assert not estimate.available
    assert estimate.seconds is None
    assert estimate.reason == REASON_INSUFFICIENT_COVERAGE
    assert estimate.coverage == pytest.approx(1 / 3)
    assert estimate.payload()["estimated_serial_seconds"] is None


def test_estimate_without_a_table_says_so(tmp_path: Path) -> None:
    estimate = estimate_serial_seconds(
        ["tests/test_a.py"], directory=tmp_path / "nope", environ={}
    )
    assert not estimate.available
    assert estimate.reason == REASON_NO_TABLE
    assert estimate.missing_count == 1


def test_estimate_of_an_empty_selection_is_a_measured_zero() -> None:
    estimate = estimate_serial_seconds([], table=TimingTable(), environ={})
    assert estimate.available
    assert estimate.seconds == 0.0
    assert estimate.reason == REASON_EMPTY_SELECTION


def test_estimate_is_disabled_by_the_switch(timings_dir: Path) -> None:
    _write_recording(timings_dir, {"tests/test_a.py": 1.0}, minute=1)
    estimate = estimate_serial_seconds(
        ["tests/test_a.py"],
        directory=timings_dir,
        environ={TIMINGS_DISABLED_ENV: "1"},
    )
    assert not estimate.available
    assert estimate.table.empty


def test_estimate_reads_the_table_off_disk(timings_dir: Path) -> None:
    _write_recording(timings_dir, {"tests/test_a.py": 12.5}, minute=1)
    estimate = estimate_serial_seconds(
        ["tests/test_a.py"], directory=timings_dir, environ={}
    )
    assert estimate.seconds == pytest.approx(12.5)
    assert estimate.payload()["table"]["identity"] == estimate.table.identity


def test_min_coverage_falls_back_on_nonsense() -> None:
    assert min_coverage({}) == DEFAULT_MIN_COVERAGE
    assert min_coverage({MIN_COVERAGE_ENV: "0.25"}) == pytest.approx(0.25)
    assert min_coverage({MIN_COVERAGE_ENV: "banana"}) == DEFAULT_MIN_COVERAGE
    assert min_coverage({MIN_COVERAGE_ENV: "4"}) == DEFAULT_MIN_COVERAGE


def test_min_coverage_override_admits_a_sparser_table() -> None:
    table = TimingTable(durations={"tests/test_a.py": 3.0})
    estimate = estimate_serial_seconds(
        ["tests/test_a.py", "tests/test_b.py"],
        table=table,
        environ={MIN_COVERAGE_ENV: "0.5"},
    )
    assert estimate.available
    assert estimate.seconds == pytest.approx(6.0)


# --------------------------------------------------------------------------
# The recording plugin
# --------------------------------------------------------------------------


class _Report:
    """The three fields the recorder reads off a pytest report."""

    def __init__(self, nodeid: str, duration: float) -> None:
        self.nodeid = nodeid
        self.duration = duration


def test_recorder_sums_every_phase_per_file(timings_dir: Path) -> None:
    recorder = FileDurationRecorder(timings_dir, mode="fast", worker_count=28)
    for phase_duration in (0.25, 1.0, 0.25):
        recorder.pytest_runtest_logreport(
            _Report("tests/test_a.py::test_one", phase_duration)  # type: ignore[arg-type]
        )
    recorder.pytest_runtest_logreport(
        _Report("tests/test_a.py::test_two", 0.5)  # type: ignore[arg-type]
    )
    recorder.pytest_runtest_logreport(
        _Report("tests/test_b.py::test_three", 2.0)  # type: ignore[arg-type]
    )
    assert recorder.durations == {"tests/test_a.py": 2.0, "tests/test_b.py": 2.0}

    recorder.pytest_sessionfinish(0)
    table = load_timing_table(timings_dir)
    assert table.durations == {"tests/test_a.py": 2.0, "tests/test_b.py": 2.0}
    payload = json.loads(recording_paths(timings_dir)[0].read_text(encoding="utf-8"))
    assert payload["worker_count"] == 28


def test_recorder_counts_a_collection_error_against_its_file(
    timings_dir: Path,
) -> None:
    recorder = FileDurationRecorder(timings_dir, mode="fast")
    recorder.pytest_collectreport(_Report("tests/test_a.py", 0.75))  # type: ignore[arg-type]
    recorder.pytest_collectreport(_Report("", 5.0))  # type: ignore[arg-type]
    assert recorder.durations == {"tests/test_a.py": 0.75}


def test_recorder_writes_nothing_when_nothing_ran(timings_dir: Path) -> None:
    FileDurationRecorder(timings_dir, mode="fast").pytest_sessionfinish(0)
    assert recording_paths(timings_dir) == []


def test_recorder_never_fails_a_green_run(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where the directory should be\n", encoding="utf-8")
    recorder = FileDurationRecorder(blocked / "timings", mode="fast")
    recorder.pytest_runtest_logreport(
        _Report("tests/test_a.py::test_one", 1.0)  # type: ignore[arg-type]
    )
    recorder.pytest_sessionfinish(0)


def test_recorder_request_is_consumed_so_children_do_not_inherit_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(
        TIMINGS_RECORD_ENV, json.dumps({"directory": str(tmp_path), "mode": "fast"})
    )
    request = _recorder_request()
    assert request is not None and request["directory"] == str(tmp_path)
    assert _recorder_request() is None


@pytest.mark.parametrize("raw", ["", "{", json.dumps({"mode": "fast"})])
def test_recorder_request_rejects_an_unusable_payload(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv(TIMINGS_RECORD_ENV, raw)
    assert _recorder_request() is None


# --------------------------------------------------------------------------
# What the selector records
# --------------------------------------------------------------------------


def test_manifest_records_an_unavailable_estimate_without_a_table(
    tmp_path: Path,
) -> None:
    root = build_fixture_repo(tmp_path)
    store = install_fresh_baseline(root)
    _touch(root, "src/pkg/a.py")
    selection = select_tests(
        root,
        SelectionOptions(base_ref="HEAD", use_cache=False),
        contexts_store=store,
        timings_store=store,
    )
    assert selection.selected
    timings = selection.manifest["timings"]
    assert timings["available"] is False
    assert timings["reason"] == REASON_NO_TABLE
    assert timings["estimated_serial_seconds"] is None


def test_manifest_records_the_estimate_when_the_table_covers_the_selection(
    tmp_path: Path,
) -> None:
    root = build_fixture_repo(tmp_path)
    store = install_fresh_baseline(root)
    _touch(root, "src/pkg/a.py")
    options = SelectionOptions(base_ref="HEAD", use_cache=False)
    first = select_tests(root, options, contexts_store=store, timings_store=store)
    _write_recording(
        timings_directory(store, {}),
        dict.fromkeys(first.selected, 3.0),
        minute=1,
    )

    second = select_tests(root, options, contexts_store=store, timings_store=store)
    timings = second.manifest["timings"]
    assert timings["available"] is True
    assert timings["estimated_serial_seconds"] == pytest.approx(
        3.0 * len(second.selected)
    )
    assert timings["coverage"] == pytest.approx(1.0)
    assert timings["table"]["identity"] == second.timings.table.identity
    # Well inside the default budget, so the estimate changes nothing here;
    # `tests/test_test_selection.py` owns the budget rule's own assertions.
    assert timings["estimated_serial_seconds"] < options.max_serial_seconds
    assert second.selected == first.selected
    assert second.escalated == first.escalated


def test_manifest_does_not_price_an_escalated_run_at_zero(tmp_path: Path) -> None:
    root = build_fixture_repo(tmp_path)
    store = install_fresh_baseline(root)
    _touch(root, "pyproject.toml")
    selection = select_tests(
        root,
        SelectionOptions(base_ref="HEAD", use_cache=False),
        contexts_store=store,
        timings_store=store,
    )
    assert selection.escalated
    timings = selection.manifest["timings"]
    assert timings["available"] is False
    assert timings["reason"] == REASON_ESCALATED
    assert timings["estimated_serial_seconds"] is None
