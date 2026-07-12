from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _clean_sase_core_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("SASE_CORE_DIR", None)
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


def test_lint_includes_pylimit_stage() -> None:
    output = _dry_run("lint")

    assert "Checking Python file line counts" in output
    assert "just _lint-pylimit" in output


def test_check_mirrors_lint_pylimit_stage() -> None:
    output = _dry_run("check")

    assert 'tools/run_silent "lint (pylimit)"     just _lint-pylimit' in output


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


def test_public_pylimit_target_uses_private_lint_stage() -> None:
    output = _dry_run("pylimit", "900", "800", "700")

    assert "just _lint-pylimit 900 800 700" in output
