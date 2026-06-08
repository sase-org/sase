from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _clean_sase_core_env(env_vars: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("SASE_CORE_DIR", None)
    env.pop("SASE_SIBLING_REPO_SASE_CORE_DIR", None)
    env.pop("SASE_SIBLING_REPO_CORE_DIR", None)
    env.update(env_vars)
    return env


def _evaluate_sase_core_dir(env_vars: dict[str, str]) -> str:
    result = subprocess.run(
        ["just", "--justfile", str(ROOT / "Justfile"), "--evaluate", "sase_core_dir"],
        cwd=ROOT,
        env=_clean_sase_core_env(env_vars),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize(
    ("env_vars", "expected"),
    [
        (
            {
                "SASE_CORE_DIR": "/tmp/explicit-sase-core",
                "SASE_SIBLING_REPO_SASE_CORE_DIR": "/tmp/real-sibling-sase-core",
                "SASE_SIBLING_REPO_CORE_DIR": "/tmp/sibling-sase-core",
            },
            "/tmp/explicit-sase-core",
        ),
        (
            {
                "SASE_SIBLING_REPO_SASE_CORE_DIR": "/tmp/real-sibling-sase-core",
                "SASE_SIBLING_REPO_CORE_DIR": "/tmp/sibling-sase-core",
            },
            "/tmp/real-sibling-sase-core",
        ),
        (
            {"SASE_SIBLING_REPO_CORE_DIR": "/tmp/sibling-sase-core"},
            "/tmp/sibling-sase-core",
        ),
        ({}, "../sase-core"),
    ],
)
def test_justfile_sase_core_dir_precedence(
    env_vars: dict[str, str], expected: str
) -> None:
    assert _evaluate_sase_core_dir(env_vars) == expected


def test_justfile_preserves_absolute_venv_dir_override() -> None:
    result = subprocess.run(
        [
            "just",
            "--justfile",
            str(ROOT / "Justfile"),
            "--set",
            "venv_dir",
            "/tmp/sase-custom-venv",
            "--evaluate",
            "venv_dir_abs",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "/tmp/sase-custom-venv"


def test_just_test_rust_install_targets_active_venv() -> None:
    result = subprocess.run(
        [
            "just",
            "--justfile",
            str(ROOT / "Justfile"),
            "--dry-run",
            "--set",
            "venv_dir",
            "/tmp/sase-custom-venv",
            "test",
            "tests/test_run_pytest_tool.py",
            "-q",
        ],
        cwd=ROOT,
        env=_clean_sase_core_env({"SASE_CORE_DIR": "/tmp/sase-custom-core"}),
        check=True,
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr

    assert (
        'just --set venv_dir "/tmp/sase-custom-venv" '
        '--set sase_core_dir "/tmp/sase-custom-core" '
        'rust-install "/tmp/sase-custom-venv"'
    ) in output
    assert (
        "uv pip install --python /tmp/sase-custom-venv/bin/python "
        '--no-sources --reinstall-package mypy -e ".[dev]"'
    ) in output
    assert (
        "/tmp/sase-custom-venv/bin/python tools/validate_dependency_group dev"
    ) in output
    assert (
        "/tmp/sase-custom-venv/bin/python tools/validate_dependency_group visual"
    ) in output
    assert (
        "uv pip install --python /tmp/sase-custom-venv/bin/python "
        '--no-sources -e ".[dev,visual]"'
    ) in output
