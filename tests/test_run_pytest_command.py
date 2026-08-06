"""Argument normalization and pytest command construction in `tools/run_pytest`.

These tests pin what the runner hands to pytest: how invocation-relative
selectors become repo-relative ones, which marker expression each mode selects,
and when xdist is engaged or deliberately suppressed.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests._run_pytest_fixtures import load_run_pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]


def test_normalizes_invocation_relative_file_selector() -> None:
    runner = load_run_pytest()

    result = runner._normalize_args(["test_repeat_launcher.py"], ROOT / "tests")

    assert result == ["tests/test_repeat_launcher.py"]


def test_normalizes_invocation_relative_node_selector() -> None:
    runner = load_run_pytest()

    result = runner._normalize_args(
        [
            "test_repeat_launcher.py::TestExtractRepeatAndName::test_parses_repeat_and_name"
        ],
        ROOT / "tests",
    )

    assert result == [
        "tests/test_repeat_launcher.py::TestExtractRepeatAndName::test_parses_repeat_and_name"
    ]


def test_preserves_repo_relative_selector() -> None:
    runner = load_run_pytest()

    result = runner._normalize_args(["tests/test_repeat_launcher.py"], ROOT / "tests")

    assert result == ["tests/test_repeat_launcher.py"]


def test_strips_just_separator_and_preserves_keyword_expression() -> None:
    runner = load_run_pytest()

    result = runner._normalize_args(
        ["--", "-k", "test_repeat_launcher.py", "test_repeat_launcher.py"],
        ROOT / "tests",
    )

    assert result == [
        "-k",
        "test_repeat_launcher.py",
        "tests/test_repeat_launcher.py",
    ]


def test_visual_mode_selects_visual_marker() -> None:
    runner = load_run_pytest()

    result = runner._pytest_command("visual", ["tests/ace/tui/visual"])

    assert result[0:3] == [runner.sys.executable, "-m", "pytest"]
    assert result[-3:] == [
        "-m",
        runner.VISUAL_MARKER_EXPRESSION,
        "tests/ace/tui/visual",
    ]


def test_fast_mode_selects_not_slow_and_not_visual_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_run_pytest()
    monkeypatch.delenv(runner.PYTEST_DIST_ENV, raising=False)

    result = runner._pytest_command("fast", [])

    assert "-n" in result
    assert "--dist=worksteal" in result
    assert result[-2:] == ["-m", runner.FAST_MARKER_EXPRESSION]
    assert result[-1] == "not slow and not visual"


def test_command_uses_granted_worker_count_and_worksteal_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_run_pytest()
    monkeypatch.delenv(runner.PYTEST_DIST_ENV, raising=False)

    result = runner._pytest_command("fast", [], worker_count=7)

    assert result[3:6] == ["-n", "7", "--dist=worksteal"]


def test_loadfile_distribution_environment_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_DIST_ENV, "loadfile")

    result = runner._pytest_command("fast", [], worker_count=7)

    assert result[3:6] == ["-n", "7", "--dist=loadfile"]


@pytest.mark.parametrize("invalid", ["", "load", "work-steal", "each"])
def test_distribution_override_rejects_unsupported_modes(
    monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_DIST_ENV, invalid)

    with pytest.raises(
        pytest.UsageError,
        match=r"SASE_PYTEST_DIST must be one of: loadfile, worksteal",
    ):
        runner._configured_distribution_mode()


def test_rejects_xdist_count_that_could_bypass_grant() -> None:
    runner = load_run_pytest()

    with pytest.raises(pytest.UsageError, match="SASE_PYTEST_WORKERS"):
        runner._reject_numprocesses_args(["tests", "-n", "12"])


def test_inline_snapshot_fix_disables_default_xdist() -> None:
    runner = load_run_pytest()

    result = runner._pytest_command(
        "fast", ["--inline-snapshot=fix", "tests/test_run_pytest_command.py"]
    )

    assert "-n" not in result
    assert not any(arg.startswith("--dist") for arg in result)
    assert result[-2:] == ["--inline-snapshot=fix", "tests/test_run_pytest_command.py"]


def test_inline_snapshot_separate_value_disables_default_xdist() -> None:
    runner = load_run_pytest()

    result = runner._pytest_command(
        "fast",
        ["--inline-snapshot", "short-report", "tests/test_run_pytest_command.py"],
    )

    assert "-n" not in result
    assert not any(arg.startswith("--dist") for arg in result)


def test_inline_snapshot_disable_preserves_default_xdist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_run_pytest()
    monkeypatch.delenv(runner.PYTEST_DIST_ENV, raising=False)

    result = runner._pytest_command(
        "fast", ["--inline-snapshot=disable", "tests/test_run_pytest_command.py"]
    )

    assert "-n" in result
    assert "--dist=worksteal" in result


def test_inline_snapshot_fix_shortcut_disables_default_xdist() -> None:
    runner = load_run_pytest()

    result = runner._pytest_command(
        "fast", ["--fix", "tests/test_run_pytest_command.py"]
    )

    assert "-n" not in result
    assert not any(arg.startswith("--dist") for arg in result)


def test_slow_mode_selects_slow_marker() -> None:
    runner = load_run_pytest()

    result = runner._pytest_command("slow", ["tests/perf"])

    assert result[-3:] == ["-m", runner.SLOW_MARKER_EXPRESSION, "tests/perf"]


def test_terminal_smoke_mode_selects_marker_and_stays_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_DIST_ENV, "invalid-but-unused")

    result = runner._pytest_command(
        "terminal-smoke", ["tests/ace/tui/terminal_smoke"], worker_count=7
    )

    assert "-n" not in result
    assert not any(arg.startswith("--dist") for arg in result)
    assert result[-3:] == [
        "-m",
        runner.TERMINAL_SMOKE_MARKER_EXPRESSION,
        "tests/ace/tui/terminal_smoke",
    ]


def test_cov_mode_excludes_visual_tests_matching_dedicated_visual_test_job() -> None:
    runner = load_run_pytest()

    result = runner._pytest_command("cov", [])

    assert [
        "-m",
        runner.FAST_MARKER_EXPRESSION,
    ] in [result[index : index + 2] for index in range(len(result) - 1)]
    assert "--cov=src/sase" in result


def test_contexts_mode_records_which_test_ran_each_line() -> None:
    """Without ``--cov-context=test`` the database records *that* a line ran.

    Which is useless to the selector: `tests._test_selection_contexts` would
    silently contribute nothing forever.
    """
    result = load_run_pytest()._pytest_command("cov-contexts", [])

    assert "--cov-context=test" in result
    assert "--cov=src/sase" in result


def test_contexts_mode_stays_off_the_branch_coverage_config() -> None:
    """Branch coverage times contexts is a 906 MB artifact, measured.

    Line coverage answers the only question selection asks — "which tests
    executed this line" — at 49 MB. The separate config file is what keeps the
    two apart; the PR coverage leg must not pick up contexts either.
    """
    runner = load_run_pytest()

    contexts = runner._pytest_command("cov-contexts", [])
    coverage = runner._pytest_command("cov", [])

    assert f"--cov-config={runner.CONTEXTS_COVERAGE_CONFIG}" in contexts
    assert "--cov-branch" not in contexts
    assert "--cov-fail-under=50" not in contexts
    assert "--cov-context=test" not in coverage
    assert "--cov-branch" in coverage


def test_contexts_mode_pins_the_faithful_coverage_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Python 3.14's default `sysmon` core drops repeat attributions.

    It stops monitoring a location once seen, so only the first test to execute
    a line is credited with it and a full-suite baseline thins out as it runs.
    A locally recorded baseline has to be the same ground truth CI's 3.12 leg
    (already on `ctrace`) publishes.
    """
    runner = load_run_pytest()
    monkeypatch.delenv(runner.COVERAGE_CORE_ENV, raising=False)

    runner._apply_contexts_environment("cov-contexts")

    assert os.environ[runner.COVERAGE_CORE_ENV] == runner.CONTEXTS_COVERAGE_CORE


def test_other_modes_leave_the_coverage_core_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the baseline lane pays for the slower core."""
    runner = load_run_pytest()
    monkeypatch.delenv(runner.COVERAGE_CORE_ENV, raising=False)

    runner._apply_contexts_environment("cov")

    assert runner.COVERAGE_CORE_ENV not in os.environ


def test_an_explicit_coverage_core_is_respected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pinning a default is not the same as overriding a deliberate choice."""
    runner = load_run_pytest()
    monkeypatch.setenv(runner.COVERAGE_CORE_ENV, "sysmon")

    runner._apply_contexts_environment("cov-contexts")

    assert os.environ[runner.COVERAGE_CORE_ENV] == "sysmon"


def test_visual_flag_selects_visual_mode() -> None:
    runner = load_run_pytest()

    mode, args = runner._resolve_mode_and_args(
        "fast", ["--visual", "-k", "axe", "tests/ace/tui/visual"]
    )

    assert mode == "visual"
    assert args == ["-k", "axe", "tests/ace/tui/visual"]
