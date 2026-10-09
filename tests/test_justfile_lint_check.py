"""Justfile check-gate wiring and remaining recipe guards."""

from __future__ import annotations

import pytest

from tests._justfile_lint_helpers import ROOT, dry_run

pytestmark = pytest.mark.contract

_CHECK_GATE_LINES = (
    'tools/run_silent "fmt (python)"       just fmt-py-check',
    'tools/run_silent "fmt (markdown)"     just fmt-md-check',
    'tools/run_silent "lint (keep-sorted)" just lint-keep-sorted',
    'tools/run_silent "lint (ruff)"        just _lint-ruff',
    'tools/run_silent "lint (mypy)"        just _lint-mypy',
    'tools/run_silent "lint (feature flags)" just _lint-flags',
    'tools/run_silent "lint (pyscripts)"   just _lint-pyscripts',
    'tools/run_silent "lint (test waits)"  just _lint-test-waits',
    'tools/run_silent "lint (changelog)"   just _lint-changelog',
    'tools/run_silent "lint (symvision)"   just _lint-symvision',
    'tools/run_silent "SASE validation"     just validate',
    'tools/run_silent "committed plans"      just validate-committed-plans',
)


def test_check_and_check_full_recipes_exist() -> None:
    justfile = (ROOT / "Justfile").read_text()

    assert '\ncheck: (_require-tool-run "check") _setup\n' in justfile
    assert '\ncheck-full: (_require-tool-run "check-full") _setup\n' in justfile


def test_check_ends_in_the_scoped_test_lane() -> None:
    output = dry_run("check")

    assert 'tools/run_silent "test (scoped)"      just test-scoped' in output
    assert 'tools/run_silent "test"               just test' not in output
    assert output.rstrip().endswith("tools/run_silent --finish")


def test_check_full_ends_in_the_full_test_lane() -> None:
    output = dry_run("check-full")

    assert 'tools/run_silent "test cost"          just test-cost' in output
    assert "just test-scoped" not in output
    assert "just fix-tui-screenshots" in output
    assert output.rstrip().endswith("tools/run_silent --finish")


def test_check_prints_the_scoped_summary_after_run_silent_returns() -> None:
    """The scoped summary step must sit outside `run_silent`'s captured region.

    `run_silent` discards a wrapped command's captured output on success, so
    forwarding the scoped lane's summary from *inside* that call would still
    get swallowed. It has to be a separate `check` line that runs only after
    `run_silent "test (scoped)"` has already returned.
    """
    output = dry_run("check")

    scoped_line = 'tools/run_silent "test (scoped)"      just test-scoped'
    summary_line = "tools/print_scoped_summary"
    assert scoped_line in output
    assert summary_line in output
    assert output.index(scoped_line) < output.index(summary_line)


def test_check_full_does_not_print_a_scoped_summary() -> None:
    """`check-full` runs the full lane, not the scoped one; nothing to forward."""
    output = dry_run("check-full")

    assert "tools/print_scoped_summary" not in output


def test_check_full_runs_the_flake_baseline_gate_after_the_full_lane() -> None:
    output = dry_run("check-full")

    test_line = 'tools/run_silent "test cost"          just test-cost'
    gate_line = (
        'tools/run_silent "flake baseline"     just selection-health '
        "--fail-on-new-flake"
    )
    screenshot_line = "just fix-tui-screenshots"
    assert test_line in output
    assert gate_line in output
    assert screenshot_line in output
    assert output.index(test_line) < output.index(gate_line)
    assert output.index(gate_line) < output.index(screenshot_line)
    screenshot_lines = [
        line for line in output.splitlines() if "fix-tui-screenshots" in line
    ]
    assert screenshot_lines
    assert all("run_silent" not in line for line in screenshot_lines)


def test_check_lint_and_fix_do_not_run_screenshot_maintenance() -> None:
    for recipe in ("check", "lint", "fix"):
        output = dry_run(recipe)
        assert "fix-tui-screenshots" not in output
        assert "tools/fix_tui_screenshots" not in output


def test_check_and_check_full_share_an_identical_gate_list() -> None:
    """`check` and `check-full` must never drift on their non-test gates.

    The failure mode this guards against is someone adding a lint or validation
    gate to one recipe and forgetting the other.
    """
    check_output = dry_run("check")
    check_full_output = dry_run("check-full")

    for gate_line in _CHECK_GATE_LINES:
        assert gate_line in check_output
        assert gate_line in check_full_output


def test_test_scoped_runs_the_scoped_runner_mode() -> None:
    output = dry_run("test-scoped")

    assert "tools/run_pytest scoped" in output


def test_test_skips_the_visual_dependency_install() -> None:
    output = dry_run("test")

    assert "tools/run_pytest fast" in output
    assert '-e ".[dev,visual]"' not in output
    assert '-e ".[dev]"' in output


def test_test_scoped_skips_the_visual_dependency_install() -> None:
    """The scoped lane skips the pinned visual stack because it drops the visual tree.

    `_setup-visual` runs the `[dev,visual]` install; `_setup` does not. If the
    selector ever stops excluding `tests/ace/tui/visual/**`, this recipe has to
    go back to `_setup-visual` and this assertion is the tripwire.
    """
    output = dry_run("test-scoped")

    assert '-e ".[dev,visual]"' not in output
    assert '-e ".[dev]"' in output


def test_selection_health_recipe_runs_the_reporting_tool() -> None:
    output = dry_run("selection-health")

    assert "tools/selection_health" in output


def test_retired_test_wait_lint_recipe_runs_the_tool() -> None:
    output = dry_run("_lint-test-waits")

    assert "tools/check_test_wait_helpers" in output


def test_lint_includes_feature_flags_stage() -> None:
    output = dry_run("lint")

    assert "Checking feature flag registry integrity" in output
    assert "just _lint-flags" in output


def test_check_mirrors_feature_flags_stage() -> None:
    output = dry_run("check")

    assert 'tools/run_silent "lint (feature flags)" just _lint-flags' in output


def test_feature_flags_lint_recipe_uses_bead_handshake() -> None:
    output = dry_run("_lint-flags")

    assert "BD_COMMAND=tools/sase_bead" in output
    assert "SASE_SYMVISION_BEAD_STATUS_ONLY=1" in output
    assert "tools/check_feature_flags" in output


def test_validate_runs_static_feature_flag_checks() -> None:
    output = dry_run("validate")

    assert "tools/check_feature_flags --static" in output


def test_mypy_lint_recipe_runs_extensionless_tool_helper() -> None:
    output = dry_run("_lint-mypy")

    assert "tools/typecheck_extensionless_tools --mypy .venv/bin/mypy" in output


def test_selection_backtest_recipe_runs_the_backtest_tool() -> None:
    output = dry_run("selection-backtest")

    assert "tools/selection_backtest" in output


def test_selection_backtest_is_not_a_check_gate() -> None:
    """The backtest measures; it must never become something `check` waits on.

    It checks out historical commits and, under `--execute`, runs their tests.
    Neither belongs on the path an agent takes before replying.
    """
    for recipe in ("check", "check-full"):
        assert "selection_backtest" not in dry_run(recipe)


def test_refresh_contexts_baseline_recipe_runs_the_fetch_tool() -> None:
    output = dry_run("refresh-contexts-baseline")

    assert "tools/fetch_coverage_contexts" in output


def test_test_contexts_recipe_caches_the_recorded_baseline() -> None:
    """A local `cov-contexts` run is a baseline producer, not just a report.

    Without this line the only supply route for ground truth is the CI
    artifact, and a host that never fetched runs the scoped lane on the static
    closure alone.
    """
    output = dry_run("test-contexts")

    assert "tools/run_pytest cov-contexts" in output
    assert "tools/install_coverage_contexts --if-enabled" in output


def test_legacy_pyvision_wiring_is_absent() -> None:
    justfile = (ROOT / "Justfile").read_text()

    assert "_lint-pyvision" not in justfile
    assert not list((ROOT / "tools").glob("pyvision-*"))


def test_ci_telemetry_runs_scheduled_measurement_lanes_off_full_ci() -> None:
    ci_workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    full_workflow = (ROOT / ".github" / "workflows" / "full.yml").read_text()
    telemetry_workflow = (ROOT / ".github" / "workflows" / "telemetry.yml").read_text()

    assert "  schedule:\n" not in ci_workflow
    assert "  push:\n" not in ci_workflow
    assert "contention-test:\n" not in ci_workflow
    assert "coverage-contexts:\n" not in ci_workflow
    assert "  schedule:\n" in full_workflow
    assert "17 */2 * * *" in full_workflow
    assert "uses: ./.github/workflows/ci.yml" in full_workflow
    assert "  schedule:\n" in telemetry_workflow
    assert "47 */6 * * *" in telemetry_workflow
    assert "contention-test:\n" in telemetry_workflow
    assert "coverage-contexts:\n" in telemetry_workflow
    assert "test-cost:\n" in telemetry_workflow
    assert "SASE_CONTENTION_REPEAT=1 just test-contention" in telemetry_workflow
