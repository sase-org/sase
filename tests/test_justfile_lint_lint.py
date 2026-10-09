"""Justfile lint-recipe wiring: lint stages, fix, and validation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests._justfile_lint_helpers import (
    ROOT,
    clean_sase_core_env,
    copy_justfile,
    dry_run,
)

pytestmark = pytest.mark.contract


def _install_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def test_lint_includes_toobig_stage() -> None:
    """CI enforces the `toobig` gate through `just lint` after `check` skips it."""
    output = dry_run("lint")

    assert "Checking Python file line counts" in output
    assert "just _lint-toobig" in output


def test_lint_includes_symvision_stage() -> None:
    output = dry_run("lint")

    assert "Checking for unused Python definitions" in output
    assert "just _lint-symvision" in output


def test_lint_includes_retired_test_wait_stage() -> None:
    output = dry_run("lint")

    assert "Checking retired test wait helpers" in output
    assert "just _lint-test-waits" in output


def test_check_and_check_full_skip_toobig_stage() -> None:
    for recipe in ("check", "check-full"):
        output = dry_run(recipe)

        assert "_lint-toobig" not in output
        assert "lint (toobig)" not in output


def test_check_mirrors_lint_symvision_stage() -> None:
    output = dry_run("check")

    assert 'tools/run_silent "lint (symvision)"   just _lint-symvision' in output


def test_check_mirrors_retired_test_wait_stage() -> None:
    output = dry_run("check")

    assert 'tools/run_silent "lint (test waits)"  just _lint-test-waits' in output


def test_lint_does_not_run_sase_validation() -> None:
    output = dry_run("lint")

    assert "Running SASE validation" not in output
    assert "just validate" not in output


def test_fix_uses_formatter_venv_without_application_setup(tmp_path: Path) -> None:
    copy_justfile(tmp_path)
    calls = tmp_path / "calls.log"
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "sample.yml").write_text("key: value\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "add", "sample.yml"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["uv", "venv", ".venv-format"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    site_packages = subprocess.run(
        [
            str(tmp_path / ".venv-format/bin/python"),
            "-c",
            "import site; print(site.getsitepackages()[0])",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (Path(site_packages) / "yaml.py").write_text("", encoding="utf-8")
    (tmp_path / "tools/render_model_docs").write_text(
        "from pathlib import Path\n"
        "import os\n"
        "with Path(os.environ['JUST_SPY_FILE']).open('a', encoding='utf-8') as f:\n"
        "    f.write('format-python tools/render_model_docs\\n')\n",
        encoding="utf-8",
    )

    _install_executable(
        tmp_path / ".venv/bin/python",
        'echo forbidden-app-python >> "$JUST_SPY_FILE"\nexit 91\n',
    )
    _install_executable(
        tmp_path / ".venv-format/bin/ruff",
        'echo ruff "$@" >> "$JUST_SPY_FILE"\nexit 0\n',
    )
    _install_executable(
        tmp_path / ".venv-format/bin/keep-sorted",
        'echo keep-sorted "$@" >> "$JUST_SPY_FILE"\nexit 0\n',
    )
    _install_executable(
        tmp_path / "node_modules/.bin/prettier",
        'echo prettier "$@" >> "$JUST_SPY_FILE"\nexit 0\n',
    )

    subprocess.run(
        ["just", "--justfile", str(tmp_path / "Justfile"), "fix"],
        cwd=tmp_path,
        env=clean_sase_core_env() | {"JUST_SPY_FILE": str(calls)},
        check=True,
        capture_output=True,
        text=True,
    )

    recorded = calls.read_text(encoding="utf-8")
    assert "ruff format src/ tests/" in recorded
    assert "ruff check --fix src/ tests/" in recorded
    assert "format-python tools/render_model_docs" in recorded
    assert "prettier --write **/*.md" in recorded
    assert "keep-sorted sample.yml" in recorded
    assert "forbidden-app-python" not in recorded


def test_formatter_recipes_honor_custom_format_venv_dir() -> None:
    output = dry_run("--set", "format_venv_dir", "custom-format", "fmt-py")

    assert "custom-format/bin/ruff format src/ tests/" in output
    assert ".venv/bin/ruff format" not in output


def test_check_retains_sase_validation_stage() -> None:
    output = dry_run("check")

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
    output = dry_run("toobig", "900", "800", "700")

    assert "just _lint-toobig 900 800 700" in output


def test_public_symvision_target_uses_private_lint_stage() -> None:
    output = dry_run("symvision", "--help")

    assert "just _lint-symvision --help" in output


def test_private_symvision_stage_uses_published_cli() -> None:
    output = dry_run("_lint-symvision", "--help")

    assert "BD_COMMAND=tools/sase_bead" in output
    assert ".venv/bin/symvision src/sase" in output
    assert "--help" in output
    assert "python tools/pyvision" not in output
