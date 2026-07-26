"""Tests for the session-scoped system-temp leakage guard."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from tests import _tmp_leak_guard
from tests._tmp_leak_guard import (
    DISABLED_ENV,
    IGNORE_ENV,
    PYTEST_TMP_REDIRECTED_ENV,
    find_leaked_entries,
    finish_tmp_leak_guard,
    format_leak_report,
    ignore_patterns,
    report_tmp_leak_guard,
    snapshot_temp_entries,
    start_tmp_leak_guard,
    watched_temp_directories,
)


class _FakeConfig:
    """A stand-in for ``pytest.Config`` that only carries guard attributes."""


class _FakeSession:
    def __init__(self, config: _FakeConfig, exitstatus: int) -> None:
        self.config = config
        self.exitstatus = exitstatus


class _FakeTerminalReporter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write_sep(self, _separator: str, title: str, **_markup: Any) -> None:
        self.lines.append(f"=== {title}")

    def write_line(self, line: str) -> None:
        self.lines.append(line)


def _session(config: _FakeConfig, exitstatus: int = int(pytest.ExitCode.OK)) -> Any:
    return _FakeSession(config, exitstatus)


def _guarded_config(monkeypatch: pytest.MonkeyPatch, *roots: Path) -> Any:
    monkeypatch.delenv(DISABLED_ENV, raising=False)
    monkeypatch.setattr(_tmp_leak_guard, "watched_temp_directories", lambda: roots)
    config = _FakeConfig()
    start_tmp_leak_guard(_session(config))
    return config


def test_watched_directories_follow_the_effective_temp_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    monkeypatch.setenv(PYTEST_TMP_REDIRECTED_ENV, "1")
    monkeypatch.setattr(
        _tmp_leak_guard.tempfile, "gettempdir", lambda: str(scratch_root)
    )
    monkeypatch.setenv("SASE_TMPDIR", str(tmp_path / "absent-managed"))

    assert watched_temp_directories() == (scratch_root.resolve(),)


def test_watched_directories_skip_a_missing_temp_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(PYTEST_TMP_REDIRECTED_ENV, "1")
    monkeypatch.setattr(
        _tmp_leak_guard.tempfile, "gettempdir", lambda: str(tmp_path / "absent")
    )
    monkeypatch.setenv("SASE_TMPDIR", str(tmp_path / "absent-managed"))

    assert watched_temp_directories() == ()


def test_watched_directories_include_the_unsandboxed_managed_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scratch_root = tmp_path / "scratch"
    managed_root = tmp_path / "managed"
    for directory in (scratch_root, managed_root):
        directory.mkdir()
    monkeypatch.setenv(PYTEST_TMP_REDIRECTED_ENV, "1")
    monkeypatch.setattr(
        _tmp_leak_guard.tempfile, "gettempdir", lambda: str(scratch_root)
    )
    monkeypatch.setenv("SASE_TMPDIR", str(managed_root))

    assert watched_temp_directories() == (
        scratch_root.resolve(),
        managed_root.resolve(),
    )


def test_watched_directories_deduplicate_a_shared_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setenv(PYTEST_TMP_REDIRECTED_ENV, "1")
    monkeypatch.setattr(_tmp_leak_guard.tempfile, "gettempdir", lambda: str(shared))
    monkeypatch.setenv("SASE_TMPDIR", str(shared))

    assert watched_temp_directories() == (shared.resolve(),)


@pytest.mark.parametrize("value", [None, "0"])
def test_watched_directories_are_inert_without_pytest_tmp_redirect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None
) -> None:
    scratch_root = tmp_path / "scratch"
    managed_root = tmp_path / "managed"
    for directory in (scratch_root, managed_root):
        directory.mkdir()
    if value is None:
        monkeypatch.delenv(PYTEST_TMP_REDIRECTED_ENV, raising=False)
    else:
        monkeypatch.setenv(PYTEST_TMP_REDIRECTED_ENV, value)
    monkeypatch.setattr(
        _tmp_leak_guard.tempfile, "gettempdir", lambda: str(scratch_root)
    )
    monkeypatch.setenv("SASE_TMPDIR", str(managed_root))

    assert watched_temp_directories() == ()


def test_agent_launch_scratch_from_other_processes_is_ignored(
    tmp_path: Path,
) -> None:
    baseline: dict[Path, frozenset[str]] = {tmp_path: frozenset()}
    final = {
        tmp_path: frozenset(
            {
                "ace-profiles",
                "ace_profile_260725_144000.txt",
                "launch-prompts",
                "sase_ace_prompt_AbCdEf.md",
            }
        )
    }

    assert find_leaked_entries(baseline, final) == {}


def test_snapshot_reports_entry_names(tmp_path: Path) -> None:
    (tmp_path / "leaked.sase.lock").touch()
    (tmp_path / "nested").mkdir()

    snapshot = snapshot_temp_entries([tmp_path])

    assert snapshot == {tmp_path: frozenset({"leaked.sase.lock", "nested"})}


def test_snapshot_tolerates_missing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "absent"

    assert snapshot_temp_entries([missing]) == {missing: frozenset()}


def test_find_leaked_entries_reports_only_new_unignored_names(tmp_path: Path) -> None:
    baseline = {tmp_path: frozenset({"pre-existing"})}
    final = {
        tmp_path: frozenset(
            {"pre-existing", "pytest-of-bryan", "tmpab12cd34", "spec.sase.lock"}
        )
    }

    leaks = find_leaked_entries(baseline, final)

    assert leaks == {tmp_path: ("spec.sase.lock", "tmpab12cd34")}


def test_find_leaked_entries_ignores_removed_and_foreign_entries(
    tmp_path: Path,
) -> None:
    baseline = {tmp_path: frozenset({"gone", "claude-1000"})}
    final = {tmp_path: frozenset({"claude-1000", "systemd-private-abc", ".Trash-1000"})}

    assert find_leaked_entries(baseline, final) == {}


def test_ignore_patterns_extend_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(IGNORE_ENV, f"my-scratch-*{os.pathsep} other-*")

    patterns = ignore_patterns()

    assert patterns[: len(_tmp_leak_guard.FOREIGN_ENTRY_PATTERNS)] == (
        _tmp_leak_guard.FOREIGN_ENTRY_PATTERNS
    )
    assert patterns[-2:] == ("my-scratch-*", "other-*")


def test_leak_report_names_entries_and_truncates(tmp_path: Path) -> None:
    names = tuple(f"tmp{index:04d}" for index in range(25))

    report = format_leak_report({tmp_path: names})

    assert f"{tmp_path} (25 new):" in report
    assert "    - tmp0000" in report
    assert "    ... and 5 more" in report
    assert DISABLED_ENV in report


def test_guard_fails_session_and_names_leaked_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _guarded_config(monkeypatch, tmp_path)
    (tmp_path / "leaked.sase.lock").touch()

    session = _session(config)
    finish_tmp_leak_guard(session)

    assert session.exitstatus == int(pytest.ExitCode.TESTS_FAILED)
    reporter: Any = _FakeTerminalReporter()
    report_tmp_leak_guard(config, reporter)
    assert any("leaked.sase.lock" in line for line in reporter.lines)


def test_guard_passes_on_a_clean_suite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _guarded_config(monkeypatch, tmp_path)
    (tmp_path / "pytest-of-bryan").mkdir()

    session = _session(config)
    finish_tmp_leak_guard(session)

    assert session.exitstatus == int(pytest.ExitCode.OK)
    reporter: Any = _FakeTerminalReporter()
    report_tmp_leak_guard(config, reporter)
    assert reporter.lines == []


def test_guard_preserves_an_existing_failure_exit_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _guarded_config(monkeypatch, tmp_path)
    (tmp_path / "leaked.sase.lock").touch()

    session = _session(config, exitstatus=int(pytest.ExitCode.INTERRUPTED))
    finish_tmp_leak_guard(session)

    assert session.exitstatus == int(pytest.ExitCode.INTERRUPTED)


def test_guard_is_disabled_by_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(DISABLED_ENV, "1")
    monkeypatch.setattr(
        _tmp_leak_guard, "watched_temp_directories", lambda: (tmp_path,)
    )
    config: Any = _FakeConfig()

    start_tmp_leak_guard(_session(config))
    (tmp_path / "leaked.sase.lock").touch()
    session = _session(config)
    finish_tmp_leak_guard(session)

    assert session.exitstatus == int(pytest.ExitCode.OK)


def test_guard_skips_xdist_workers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(DISABLED_ENV, raising=False)
    monkeypatch.setattr(
        _tmp_leak_guard, "watched_temp_directories", lambda: (tmp_path,)
    )
    config: Any = _FakeConfig()
    config.workerinput = {"workerid": "gw0"}

    start_tmp_leak_guard(_session(config))
    (tmp_path / "leaked.sase.lock").touch()
    session = _session(config)
    finish_tmp_leak_guard(session)

    assert session.exitstatus == int(pytest.ExitCode.OK)


def test_finish_without_a_baseline_is_a_no_op() -> None:
    session = _session(_FakeConfig())

    finish_tmp_leak_guard(session)

    assert session.exitstatus == int(pytest.ExitCode.OK)
