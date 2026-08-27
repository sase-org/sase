"""Tests for `SASE_TEST_SHARD` support wired into `tools/run_pytest`.

The master gate is the one caller that sets `SASE_TEST_SHARD`; every other
caller must see identical behavior whether it is unset or explicitly empty.
These tests pin that boundary, plus the health/timings recording split a
sharded run needs: a shard is partial evidence about the whole suite, so its
failures must not land in the durable selection-health store, but its
per-test durations are exactly as valid as the whole lane's and must still
refresh the timing tables.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest

from tests._run_pytest_fixtures import (
    isolate_run_pytest_environment,  # noqa: F401 (registers autouse env-isolation fixture)
    load_run_pytest,
)
from tests._test_selection_health_store import STORE_ENV


# Deliberately not `pytest.mark.contract`, unlike its `test_run_pytest_*.py`
# siblings: tests/test_contract_manifest.py caps the curated set at a
# measured serial-second budget, and adding to it is its own curation
# decision (see plans/202608/test_suite_tier1.md), not a side effect of
# adding sharding. This module still reaches every scoped or full-lane run
# that touches tools/run_pytest or tests/_test_shards.py.


class _ExecCalled(Exception):
    pass


def _prepare(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(tmp_path / "scratch"))
    monkeypatch.delenv(runner.HEALTH_DISABLED_ENV, raising=False)
    monkeypatch.setattr(runner, "_parallel_worker_grant", lambda: (2, None))


def _capture_command(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> list[str]:
    observed: dict[str, object] = {}

    def _execv(_executable: str, command: list[str]) -> None:
        observed["command"] = command
        raise _ExecCalled

    monkeypatch.setattr(runner.os, "execv", _execv)
    with pytest.raises(_ExecCalled):
        runner.main(argv)
    command = observed["command"]
    assert isinstance(command, list)
    return command


def _forbid_launch(runner: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    def _unexpected_execv(_executable: str, _command: list[str]) -> None:
        raise AssertionError("run_pytest launched pytest unexpectedly")

    def _unexpected_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("run_pytest launched pytest unexpectedly")

    monkeypatch.setattr(runner.os, "execv", _unexpected_execv)
    monkeypatch.setattr(runner.subprocess, "run", _unexpected_run)


def test_valid_shard_spec_selects_and_appends_the_assigned_shard_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    _prepare(runner, monkeypatch, tmp_path)
    monkeypatch.setenv(runner.SHARD_ENV, "1/6")

    command = _capture_command(runner, monkeypatch, ["fast"])

    files = runner.discover_test_files(runner.REPO_ROOT)
    table = runner.load_shard_timings(runner.REPO_ROOT / runner.DEFAULT_TIMINGS_PATH)
    expected = runner.shard_files(files, runner.ShardSpec(index=1, count=6), table)

    assert expected.files
    assert command[-len(expected.files) :] == list(expected.files)
    assert runner.HEALTH_PLUGIN_MODULE not in command

    stderr = capsys.readouterr().err
    assert "shard 1/6:" in stderr


@pytest.mark.parametrize(
    "value",
    ["0/6", "7/6", "abc", "1-6", "1/6/2", "1/0"],
)
def test_malformed_or_out_of_range_shard_specs_are_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str
) -> None:
    runner = load_run_pytest()
    _prepare(runner, monkeypatch, tmp_path)
    _forbid_launch(runner, monkeypatch)
    monkeypatch.setenv(runner.SHARD_ENV, value)

    assert runner.main(["fast"]) == int(pytest.ExitCode.USAGE_ERROR)


@pytest.mark.parametrize("mode", ["cov", "slow", "terminal-smoke"])
def test_sharding_is_only_supported_in_fast_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    runner = load_run_pytest()
    _prepare(runner, monkeypatch, tmp_path)
    _forbid_launch(runner, monkeypatch)
    monkeypatch.setenv(runner.SHARD_ENV, "1/2")

    assert runner.main([mode]) == int(pytest.ExitCode.USAGE_ERROR)


def test_sharding_rejects_an_explicit_test_selector(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    _prepare(runner, monkeypatch, tmp_path)
    _forbid_launch(runner, monkeypatch)
    monkeypatch.setenv(runner.SHARD_ENV, "1/2")

    assert runner.main(["fast", "tests/test_run_pytest_shards.py"]) == int(
        pytest.ExitCode.USAGE_ERROR
    )


@pytest.mark.parametrize("value", [None, ""])
def test_unset_or_empty_shard_env_preserves_existing_fast_mode_behavior(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None
) -> None:
    runner = load_run_pytest()
    _prepare(runner, monkeypatch, tmp_path)
    if value is None:
        monkeypatch.delenv(runner.SHARD_ENV, raising=False)
    else:
        monkeypatch.setenv(runner.SHARD_ENV, value)

    command = _capture_command(runner, monkeypatch, ["fast"])

    # Unsharded fast mode still arms both the full-lane health recorder and
    # the timings recorder, in that order -- see test_run_pytest_health.py.
    assert command[-2:] == ["-p", runner.HEALTH_PLUGIN_MODULE]
    assert runner.TIMINGS_PLUGIN_MODULE in command


def test_sharded_run_suppresses_full_lane_health_recording(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    _prepare(runner, monkeypatch, tmp_path)
    monkeypatch.setenv(runner.SHARD_ENV, "1/6")

    command = _capture_command(runner, monkeypatch, ["fast"])

    assert runner.HEALTH_PLUGIN_MODULE not in command
    assert runner.os.environ.get(runner.RECORD_ENV) is None


def test_sharded_run_still_records_per_file_timings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    _prepare(runner, monkeypatch, tmp_path)
    monkeypatch.setenv(runner.SHARD_ENV, "2/6")

    command = _capture_command(runner, monkeypatch, ["fast"])

    assert runner.TIMINGS_PLUGIN_MODULE in command
    assert runner.os.environ.get(runner.TIMINGS_RECORD_ENV) is not None
