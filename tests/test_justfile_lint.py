from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]


def _clean_sase_core_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("SASE_CORE_DIR", None)
    env.pop("SASE_CORE_WHEEL", None)
    env.pop("SASE_LINKED_REPO_SASE_CORE_DIR", None)
    env.pop("SASE_LINKED_REPO_SASE_CORE_PRIMARY_DIR", None)
    env.pop("SASE_SIBLING_REPO_SASE_CORE_DIR", None)
    env.pop("SASE_SIBLING_REPO_SASE_CORE_PRIMARY_DIR", None)
    env.pop("SASE_SIBLING_REPO_CORE_DIR", None)
    env.pop("SASE_SIBLING_REPO_CORE_PRIMARY_DIR", None)
    return env


def _dry_run(*args: str) -> str:
    result = subprocess.run(
        ["just", "--justfile", str(ROOT / "Justfile"), "--dry-run", *args],
        cwd=ROOT,
        env=_clean_sase_core_env(),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr


def _copy_justfile(root: Path) -> None:
    shutil.copyfile(ROOT / "Justfile", root / "Justfile")


def _install_spy_python(root: Path) -> None:
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$JUST_SPY_FILE"\nexit 0\n',
        encoding="utf-8",
    )
    python.chmod(0o755)


def test_lint_includes_toobig_stage() -> None:
    output = _dry_run("lint")

    assert "Checking Python file line counts" in output
    assert "just _lint-toobig" in output


def test_lint_includes_symvision_stage() -> None:
    output = _dry_run("lint")

    assert "Checking for unused Python definitions" in output
    assert "just _lint-symvision" in output


def test_lint_includes_retired_test_wait_stage() -> None:
    output = _dry_run("lint")

    assert "Checking retired test wait helpers" in output
    assert "just _lint-test-waits" in output


def test_check_mirrors_lint_toobig_stage() -> None:
    output = _dry_run("check")

    assert 'tools/run_silent "lint (toobig)"      just _lint-toobig' in output


def test_check_mirrors_lint_symvision_stage() -> None:
    output = _dry_run("check")

    assert 'tools/run_silent "lint (symvision)"   just _lint-symvision' in output


def test_check_mirrors_retired_test_wait_stage() -> None:
    output = _dry_run("check")

    assert 'tools/run_silent "lint (test waits)"  just _lint-test-waits' in output


def test_lint_does_not_run_sase_validation() -> None:
    output = _dry_run("lint")

    assert "Running SASE validation" not in output
    assert "just validate" not in output


def test_check_retains_sase_validation_stage() -> None:
    output = _dry_run("check")

    assert 'tools/run_silent "SASE validation"     just validate' in output


def test_ci_lint_job_retains_sase_validation_stage() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "      - name: SASE validation\n        run: just validate\n" in workflow


def test_ci_lint_job_derives_sdd_sidecars_from_config() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "run: ./.venv/bin/python tools/ci_bootstrap_sidecars\n" in workflow
    # The sidecar environment comes from sase/sase.yml. Hand-mirroring the
    # sidecar list and the store record here drifted every time the config
    # changed, which is what broke `sase validate` on every master run.
    assert "repository: sase-org/sase--plans" not in workflow
    assert "repository: sase-org/sase--beads" not in workflow
    assert "repository: sase-org/sase--research" not in workflow
    assert '"storage": "sidecar_repos"' not in workflow
    assert "mkdir -p .sase" not in workflow
    assert "sase-org/sase--sdd" not in workflow


def test_public_toobig_target_uses_private_lint_stage() -> None:
    output = _dry_run("toobig", "900", "800", "700")

    assert "just _lint-toobig 900 800 700" in output


def test_public_symvision_target_uses_private_lint_stage() -> None:
    output = _dry_run("symvision", "--help")

    assert "just _lint-symvision --help" in output


def test_private_symvision_stage_uses_published_cli() -> None:
    output = _dry_run("_lint-symvision", "--help")

    assert "BD_COMMAND=tools/sase_bead" in output
    assert ".venv/bin/symvision src/sase" in output
    assert "--help" in output
    assert "python tools/pyvision" not in output


def test_setup_is_fatal_on_the_core_version_behind_bit() -> None:
    output = _dry_run("_setup")

    assert "if [ $((validation_status & 16)) -ne 0 ]" in output
    assert (
        "[setup] ERROR: the sase-core checkout is behind the sase-core-rs floor"
        in output
    )
    assert "sase repo open sase-core" in output
    assert 'if [ "${SASE_ALLOW_STALE_CORE:-}" = "1" ]' in output


def test_setup_notes_the_core_version_ahead_bit_as_normal() -> None:
    output = _dry_run("_setup")

    assert "if [ $((validation_status & 1)) -ne 0 ]" in output
    assert (
        "[setup] Note: the sase-core checkout is ahead of the published "
        "sase-core-rs window in pyproject.toml" in output
    )
    assert "no action is needed here" in output


def test_setup_propagates_the_post_rebuild_bindings_check_exit_status() -> None:
    """Without this, `_setup` silently swallows a still-stale rebuilt extension.

    `just` runs recipes under `sh -cu` (no `-e`), so a failing command that
    isn't checked doesn't fail the recipe on its own.
    """
    output = _dry_run("_setup")

    assert "tools/validate_sase_core_rs --sase-core-dir" in output
    assert "|| exit $?" in output


def test_refresh_sase_core_checkout_skips_fetch_when_stale_core_is_allowed(
    tmp_path: Path,
) -> None:
    _copy_justfile(tmp_path)
    marker = tmp_path / "python-called"
    _install_spy_python(tmp_path)

    subprocess.run(
        [
            "just",
            "--justfile",
            str(tmp_path / "Justfile"),
            "--set",
            "venv_dir",
            ".venv",
            "--set",
            "sase_core_dir",
            str(tmp_path / "sase-core"),
            "_refresh-sase-core-checkout",
        ],
        cwd=tmp_path,
        env=_clean_sase_core_env()
        | {
            "JUST_SPY_FILE": str(marker),
            "SASE_ALLOW_STALE_CORE": "1",
        },
        check=True,
        capture_output=True,
        text=True,
    )

    assert not marker.exists()


def test_refresh_sase_core_checkout_fetches_when_stale_core_is_not_allowed(
    tmp_path: Path,
) -> None:
    _copy_justfile(tmp_path)
    marker = tmp_path / "python-called"
    _install_spy_python(tmp_path)

    subprocess.run(
        [
            "just",
            "--justfile",
            str(tmp_path / "Justfile"),
            "--set",
            "venv_dir",
            ".venv",
            "--set",
            "sase_core_dir",
            str(tmp_path / "sase-core"),
            "_refresh-sase-core-checkout",
        ],
        cwd=tmp_path,
        env=_clean_sase_core_env() | {"JUST_SPY_FILE": str(marker)},
        check=True,
        capture_output=True,
        text=True,
    )

    assert "tools/refresh_linked_checkout" in marker.read_text(encoding="utf-8")


@pytest.mark.parametrize("recipe", ["rust-install", "rust-dev-install"])
def test_rust_install_recipes_skip_refresh_helper_when_stale_core_is_allowed(
    recipe: str,
) -> None:
    output = _dry_run(recipe, "/tmp/fake-venv")

    assert 'if [ "${SASE_ALLOW_STALE_CORE:-}" != "1" ]; then' in output
    assert "_refresh-sase-core-checkout" in output
    assert "maturin" in output


def test_rust_install_is_fatal_on_a_behind_status() -> None:
    output = _dry_run("rust-install", "/tmp/fake-venv")

    assert 'if [ "$status" -eq 3 ]' in output
    assert (
        "[rust-install] ERROR: the sase-core checkout is behind the sase-core-rs floor"
        in output
    )
    assert "sase repo open sase-core" in output
    assert 'if [ "${SASE_ALLOW_STALE_CORE:-}" = "1" ]' in output


def test_rust_install_notes_other_nonzero_status_as_normal() -> None:
    output = _dry_run("rust-install", "/tmp/fake-venv")

    assert 'elif [ "$status" -ne 0 ]' in output
    assert (
        "[rust-install] Note: the sase-core checkout is ahead of the published "
        "sase-core-rs window in pyproject.toml" in output
    )
    assert "no action is needed here" in output


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
    'tools/run_silent "lint (toobig)"      just _lint-toobig',
    'tools/run_silent "SASE validation"     just validate',
    'tools/run_silent "committed plans"      just validate-committed-plans',
)


def test_check_and_check_full_recipes_exist() -> None:
    justfile = (ROOT / "Justfile").read_text()

    assert "\ncheck: _setup\n" in justfile
    assert "\ncheck-full: _setup\n" in justfile


def test_check_ends_in_the_scoped_test_lane() -> None:
    output = _dry_run("check")

    assert 'tools/run_silent "test (scoped)"      just test-scoped' in output
    assert 'tools/run_silent "test"               just test' not in output


def test_check_full_ends_in_the_full_test_lane() -> None:
    output = _dry_run("check-full")

    assert 'tools/run_silent "test cost"          just test-cost' in output
    assert "just test-scoped" not in output


def test_check_prints_the_scoped_summary_after_run_silent_returns() -> None:
    """The scoped summary step must sit outside `run_silent`'s captured region.

    `run_silent` discards a wrapped command's captured output on success, so
    forwarding the scoped lane's summary from *inside* that call would still
    get swallowed. It has to be a separate `check` line that runs only after
    `run_silent "test (scoped)"` has already returned.
    """
    output = _dry_run("check")

    scoped_line = 'tools/run_silent "test (scoped)"      just test-scoped'
    summary_line = "tools/print_scoped_summary"
    assert scoped_line in output
    assert summary_line in output
    assert output.index(scoped_line) < output.index(summary_line)


def test_check_full_does_not_print_a_scoped_summary() -> None:
    """`check-full` runs the full lane, not the scoped one; nothing to forward."""
    output = _dry_run("check-full")

    assert "tools/print_scoped_summary" not in output


def test_check_full_runs_the_flake_baseline_gate_after_the_full_lane() -> None:
    output = _dry_run("check-full")

    test_line = 'tools/run_silent "test cost"          just test-cost'
    gate_line = (
        'tools/run_silent "flake baseline"     just selection-health '
        "--fail-on-new-flake"
    )
    assert test_line in output
    assert gate_line in output
    assert output.index(test_line) < output.index(gate_line)


def test_check_and_check_full_share_an_identical_gate_list() -> None:
    """`check` and `check-full` must never drift on their non-test gates.

    The failure mode this guards against is someone adding a tenth lint or
    validation gate to one recipe and forgetting the other.
    """
    check_output = _dry_run("check")
    check_full_output = _dry_run("check-full")

    for gate_line in _CHECK_GATE_LINES:
        assert gate_line in check_output
        assert gate_line in check_full_output


def test_test_scoped_runs_the_scoped_runner_mode() -> None:
    output = _dry_run("test-scoped")

    assert "tools/run_pytest scoped" in output


def test_test_scoped_skips_the_visual_dependency_install() -> None:
    """The scoped lane is Pillow-free because the selector drops the visual tree.

    `_setup-visual` runs the `[dev,visual]` install; `_setup` does not. If the
    selector ever stops excluding `tests/ace/tui/visual/**`, this recipe has to
    go back to `_setup-visual` and this assertion is the tripwire.
    """
    output = _dry_run("test-scoped")

    assert '-e ".[dev,visual]"' not in output
    assert '-e ".[dev]"' in output


def test_selection_health_recipe_runs_the_reporting_tool() -> None:
    output = _dry_run("selection-health")

    assert "tools/selection_health" in output


def test_retired_test_wait_lint_recipe_runs_the_tool() -> None:
    output = _dry_run("_lint-test-waits")

    assert "tools/check_test_wait_helpers" in output


def test_lint_includes_feature_flags_stage() -> None:
    output = _dry_run("lint")

    assert "Checking feature flag registry integrity" in output
    assert "just _lint-flags" in output


def test_check_mirrors_feature_flags_stage() -> None:
    output = _dry_run("check")

    assert 'tools/run_silent "lint (feature flags)" just _lint-flags' in output


def test_feature_flags_lint_recipe_uses_bead_handshake() -> None:
    output = _dry_run("_lint-flags")

    assert "BD_COMMAND=tools/sase_bead" in output
    assert "SASE_SYMVISION_BEAD_STATUS_ONLY=1" in output
    assert "tools/check_feature_flags" in output


def test_validate_runs_static_feature_flag_checks() -> None:
    output = _dry_run("validate")

    assert "tools/check_feature_flags --static" in output


def test_mypy_lint_recipe_runs_extensionless_tool_helper() -> None:
    output = _dry_run("_lint-mypy")

    assert "tools/typecheck_extensionless_tools --mypy .venv/bin/mypy" in output


def test_selection_backtest_recipe_runs_the_backtest_tool() -> None:
    output = _dry_run("selection-backtest")

    assert "tools/selection_backtest" in output


def test_selection_backtest_is_not_a_check_gate() -> None:
    """The backtest measures; it must never become something `check` waits on.

    It checks out historical commits and, under `--execute`, runs their tests.
    Neither belongs on the path an agent takes before replying.
    """
    for recipe in ("check", "check-full"):
        assert "selection_backtest" not in _dry_run(recipe)


def test_refresh_contexts_baseline_recipe_runs_the_fetch_tool() -> None:
    output = _dry_run("refresh-contexts-baseline")

    assert "tools/fetch_coverage_contexts" in output


def test_test_contexts_recipe_caches_the_recorded_baseline() -> None:
    """A local `cov-contexts` run is a baseline producer, not just a report.

    Without this line the only supply route for ground truth is the CI
    artifact, and a host that never fetched runs the scoped lane on the static
    closure alone.
    """
    output = _dry_run("test-contexts")

    assert "tools/run_pytest cov-contexts" in output
    assert "tools/install_coverage_contexts --if-enabled" in output


def test_legacy_pyvision_wiring_is_absent() -> None:
    justfile = (ROOT / "Justfile").read_text()

    assert "_lint-pyvision" not in justfile
    assert not list((ROOT / "tools").glob("pyvision-*"))


def test_ci_has_scheduled_contention_job_only() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "  schedule:\n" in workflow
    assert "contention-test:\n" in workflow
    assert "if: github.event_name == 'schedule'" in workflow
    assert "SASE_CONTENTION_REPEAT=3 just test-contention" in workflow
