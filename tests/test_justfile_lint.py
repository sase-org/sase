from __future__ import annotations

import os
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
    env.pop("SASE_SIBLING_REPO_SASE_CORE_DIR", None)
    env.pop("SASE_SIBLING_REPO_CORE_DIR", None)
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


def test_lint_includes_toobig_stage() -> None:
    output = _dry_run("lint")

    assert "Checking Python file line counts" in output
    assert "just _lint-toobig" in output


def test_lint_includes_symvision_stage() -> None:
    output = _dry_run("lint")

    assert "Checking for unused Python definitions" in output
    assert "just _lint-symvision" in output


def test_check_mirrors_lint_toobig_stage() -> None:
    output = _dry_run("check")

    assert 'tools/run_silent "lint (toobig)"      just _lint-toobig' in output


def test_check_mirrors_lint_symvision_stage() -> None:
    output = _dry_run("check")

    assert 'tools/run_silent "lint (symvision)"   just _lint-symvision' in output


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


_CHECK_GATE_LINES = (
    'tools/run_silent "fmt (python)"       just fmt-py-check',
    'tools/run_silent "fmt (markdown)"     just fmt-md-check',
    'tools/run_silent "lint (keep-sorted)" just lint-keep-sorted',
    'tools/run_silent "lint (ruff)"        just _lint-ruff',
    'tools/run_silent "lint (mypy)"        just _lint-mypy',
    'tools/run_silent "lint (pyscripts)"   just _lint-pyscripts',
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

    assert 'tools/run_silent "test"               just test' in output
    assert "just test-scoped" not in output


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


def test_legacy_pyvision_wiring_is_absent() -> None:
    justfile = (ROOT / "Justfile").read_text()

    assert "_lint-pyvision" not in justfile
    assert not list((ROOT / "tools").glob("pyvision-*"))
