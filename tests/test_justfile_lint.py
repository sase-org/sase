from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml


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


def test_ci_lint_job_validates_split_sdd_sidecars() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(workflow_path.read_text())
    steps = workflow["jobs"]["lint"]["steps"]

    checkouts = {
        step["with"]["repository"]: step["with"]["path"]
        for step in steps
        if step.get("uses") == "actions/checkout@v4" and "with" in step
    }
    assert checkouts == {
        "sase-org/sase--plans": "sase/repos/plans",
        "sase-org/sase--beads": "sase/repos/beads",
        "sase-org/sase--research": "sase/repos/research",
    }

    record_script = next(
        step["run"]
        for step in steps
        if step.get("name") == "Record split SDD sidecar store"
    )
    record_text = record_script.split("<<'JSON'\n", maxsplit=1)[1].split(
        "\nJSON", maxsplit=1
    )[0]
    record = json.loads(record_text)
    assert record["schema_version"] == 3
    assert record["storage"] == "sidecar_repos"
    assert set(record["sidecars"]) == {"plans", "beads", "research"}


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


def test_legacy_pyvision_wiring_is_absent() -> None:
    justfile = (ROOT / "Justfile").read_text()

    assert "_lint-pyvision" not in justfile
    assert not list((ROOT / "tools").glob("pyvision-*"))
