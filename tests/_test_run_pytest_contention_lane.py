"""Tests for contention lane selection and repeated execution."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests._contention import (
    FAILURES_ENV,
    SHARDS_ENV,
    NodeTally,
    format_tally,
    read_shard_map,
    tally_failures,
    write_failures,
)
from tests._run_pytest_fixtures import load_run_pytest
from tests._run_pytest_contention_support import install_fake_repeats
from tests._test_selection_health_store import RECORD_ENV, STORE_ENV
from tests._test_shards import discover_test_files

ROOT = Path(__file__).resolve().parents[1]


def test_contention_mode_runs_the_default_lane_selection() -> None:
    runner = load_run_pytest()

    command = runner._pytest_command(
        runner.CONTENTION_MODE, [], worker_count=26, serial=False
    )

    assert command[3:6] == ["-n", "26", "--dist=worksteal"]
    assert command[-2:] == ["-m", runner.FAST_MARKER_EXPRESSION]


def test_contention_stays_out_of_the_recorded_and_full_lane_modes() -> None:
    runner = load_run_pytest()

    assert runner.CONTENTION_MODE not in runner.FULL_LANE_MODES
    assert runner.CONTENTION_MODE not in runner.TIMINGS_RECORDING_MODES
    assert runner.CONTENTION_MODE not in runner.SERIAL_MODES
    assert runner._full_lane_recording_args(runner.CONTENTION_MODE) == []
    assert runner._timings_pytest_args(runner.CONTENTION_MODE) == []


@pytest.mark.parametrize("recipe", ["check", "check-full"])
def test_contention_is_unreachable_from_the_verification_recipes(recipe: str) -> None:
    """The soak stays opt-in: a mandatory gate must not starve the host.

    Asserted against `just --dry-run`, not the Justfile text, so an indirect
    dependency added later is caught too.
    """
    dry_run = subprocess.run(
        ["just", "--justfile", str(ROOT / "Justfile"), "--dry-run", recipe],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    output = dry_run.stdout + dry_run.stderr
    assert "test-contention" not in output
    assert "run_pytest contention" not in output


def test_repeat_runs_neither_lease_the_gate_nor_record_health(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.delenv(runner.CONTENTION_REPEAT_ENV, raising=False)
    monkeypatch.setenv(runner.CONTENTION_WORKERS_ENV, "26")
    recorded = install_fake_repeats(
        runner, monkeypatch, tmp_path, [(0, ()), (0, ()), (0, ())]
    )

    def _unexpected_lease(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the contention soak leased suite-gate tokens")

    monkeypatch.setattr(runner, "_parallel_worker_grant", _unexpected_lease)

    assert runner.main(["contention"]) == 0
    assert len(recorded) == runner.DEFAULT_CONTENTION_REPEAT
    for repeat in recorded:
        assert repeat.env["SASE_TEST_GATE_DISABLED"] == "1"
        assert repeat.env[runner.HEALTH_DISABLED_ENV] == "1"
        assert repeat.env[runner.CONTENTION_ACTIVE_ENV] == "1"
        assert RECORD_ENV not in repeat.env
        assert "-p" in repeat.command
        assert runner.CONTENTION_PLUGIN_MODULE in repeat.command
    assert runner.CONTENTION_ACTIVE_ENV not in os.environ


def test_repeats_run_hypothesis_with_the_profile_hosted_ci_uses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A local soak must not trip wall-clock health checks CI never runs.

    The hosted job inherits Hypothesis' `ci` profile from `GITHUB_ACTIONS`; a
    local soak has no such variable, and its default profile's `too_slow`
    check failed a pure property test on a 2.8 s scheduler stall.
    """
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "1")
    monkeypatch.setenv(runner.CONTENTION_WORKERS_ENV, "4")
    recorded = install_fake_repeats(runner, monkeypatch, tmp_path, [(0, ())])

    assert (
        runner.main(
            ["contention", "--", "--hypothesis-profile=default", "tests/test_a.py"]
        )
        == 0
    )
    (repeat,) = recorded
    lane_flag = f"--hypothesis-profile={runner.CONTENTION_HYPOTHESIS_PROFILE}"
    assert runner.CONTENTION_HYPOTHESIS_PROFILE == "ci"
    assert lane_flag in repeat.command
    # The caller's own profile comes later on the command line, so it wins.
    assert repeat.command.index(lane_flag) < repeat.command.index(
        "--hypothesis-profile=default"
    )


def test_repeat_count_and_selector_subset_are_honoured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "2")
    monkeypatch.setenv(runner.CONTENTION_WORKERS_ENV, "9")
    recorded = install_fake_repeats(runner, monkeypatch, tmp_path, [(0, ()), (0, ())])

    assert runner.main(["contention", "--", "tests/test_agent_lanes.py"]) == 0
    assert len(recorded) == 2
    for repeat in recorded:
        assert repeat.command[3:5] == ["-n", "9"]
        assert repeat.command[-1] == "tests/test_agent_lanes.py"
    # Each repeat gets its own record, so the tally can attribute a node to one.
    paths = {repeat.env[FAILURES_ENV] for repeat in recorded}
    assert len(paths) == 2


def test_a_whole_suite_soak_gives_each_worker_its_own_shard_of_the_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every worker collecting everything is what OOM-killed the hosted soak."""
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "2")
    monkeypatch.delenv(runner.CONTENTION_WORKERS_ENV, raising=False)
    monkeypatch.delenv(runner.PYTEST_DIST_ENV, raising=False)
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    recorded = install_fake_repeats(runner, monkeypatch, tmp_path, [(0, ()), (0, ())])

    assert runner.main(["contention"]) == 0

    # The soak's shape is unchanged: same width, same selection, same CPUs.
    shard_map = tmp_path / "contention-artifacts" / "shards.json"
    for repeat in recorded:
        assert repeat.command[3:5] == ["-n", str(runner.DEFAULT_CONTENTION_WORKERS)]
        assert "--ignore=tests/ace/tui/visual" in repeat.command
        marker = len(repeat.command) - 1 - repeat.command[::-1].index("-m")
        assert repeat.command[marker + 1] == runner.FAST_MARKER_EXPRESSION
        assert repeat.env[SHARDS_ENV] == str(shard_map)
    assert SHARDS_ENV not in os.environ
    shards = read_shard_map(shard_map)
    assert len(shards) == runner.DEFAULT_CONTENTION_WORKERS
    assert all(shards)
    # Disjoint and exhaustive over the selection the lane collects.
    assigned = [name for files in shards for name in files]
    expected = {
        name
        for name in discover_test_files(ROOT)
        if not name.startswith(
            tuple(f"{visual}/" for visual in runner.VISUAL_TEST_PATHS)
        )
    }
    assert len(assigned) == len(set(assigned))
    assert set(assigned) == expected
    output = capsys.readouterr().out
    assert f"{runner.DEFAULT_CONTENTION_WORKERS} workers, dist=sharded" in output
    assert "contention shards: each worker collects and runs its own" in output


@pytest.mark.parametrize(
    ("args", "distribution"),
    [(["--", "tests/test_agent_lanes.py"], None), ([], "loadfile")],
    ids=["explicit-path", "explicit-distribution"],
)
def test_a_caller_chosen_scope_keeps_whole_collection_on_every_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    distribution: str | None,
) -> None:
    """A subset is meant to spread over every worker; a named dist needs it."""
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "1")
    if distribution is None:
        monkeypatch.delenv(runner.PYTEST_DIST_ENV, raising=False)
    else:
        monkeypatch.setenv(runner.PYTEST_DIST_ENV, distribution)
    recorded = install_fake_repeats(runner, monkeypatch, tmp_path, [(0, ())])

    assert runner.main(["contention", *args]) == 0

    assert SHARDS_ENV not in recorded[0].env
    assert not (tmp_path / "contention-artifacts" / "shards.json").exists()
    assert f"--dist={distribution or 'worksteal'}" in recorded[0].command
    assert f"dist={distribution or 'worksteal'}" in capsys.readouterr().out


def test_red_soak_returns_the_first_repeat_exit_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "3")
    install_fake_repeats(
        runner,
        monkeypatch,
        tmp_path,
        [
            (0, ()),
            (1, ("tests/t.py::test_flaky",)),
            (1, ("tests/t.py::test_flaky", "tests/t.py::test_other")),
        ],
    )

    assert runner.main(["contention"]) == 1
    report = capsys.readouterr().out
    assert "2/3  tests/t.py::test_flaky  (repeats 2,3)" in report
    assert "1/3  tests/t.py::test_other  (repeats 3)" in report
    assert "red repeats: 2,3" in report


def test_stale_records_from_a_longer_soak_are_cleared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "1")
    install_fake_repeats(runner, monkeypatch, tmp_path, [(0, ())])
    stale = tmp_path / "contention-artifacts" / "repeat-02.json"
    write_failures(stale, ("tests/t.py::test_from_a_previous_soak",))

    assert runner.main(["contention"]) == 0
    assert not stale.exists()
    assert "test_from_a_previous_soak" not in capsys.readouterr().out


@pytest.mark.parametrize("value", ["0", "-2", "many"])
def test_invalid_repeat_count_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, value)

    assert runner.main(["contention"]) == int(pytest.ExitCode.USAGE_ERROR)


def test_numprocesses_is_rejected_with_the_lane_specific_remedy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()

    def _unexpected_run(_command: list[str], **_kwargs: object) -> None:
        raise AssertionError("the soak launched pytest despite a rejected width")

    monkeypatch.setattr(runner.subprocess, "run", _unexpected_run)

    assert runner.main(["contention", "--", "-n", "4"]) == int(
        pytest.ExitCode.USAGE_ERROR
    )
    assert runner.CONTENTION_WORKERS_ENV in capsys.readouterr().err


def test_worker_width_falls_back_to_the_general_knob_then_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_run_pytest()
    monkeypatch.delenv(runner.CONTENTION_WORKERS_ENV, raising=False)
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    assert runner._contention_worker_count() == runner.DEFAULT_CONTENTION_WORKERS

    monkeypatch.setenv("SASE_PYTEST_WORKERS", "12")
    assert runner._contention_worker_count() == 12

    monkeypatch.setenv(runner.CONTENTION_WORKERS_ENV, "40")
    assert runner._contention_worker_count() == 40
