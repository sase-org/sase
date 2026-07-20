from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _clean_sase_core_env(env_vars: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("SASE_CORE_DIR", None)
    env.pop("SASE_LINKED_REPO_SASE_CORE_DIR", None)
    env.pop("SASE_SIBLING_REPO_SASE_CORE_DIR", None)
    env.pop("SASE_SIBLING_REPO_CORE_DIR", None)
    env.update(env_vars)
    return env


@pytest.fixture
def isolated_justfile_root(tmp_path: Path) -> Path:
    shutil.copyfile(ROOT / "Justfile", tmp_path / "Justfile")
    return tmp_path


def _evaluate_sase_core_dir(env_vars: dict[str, str], *, root: Path) -> str:
    result = subprocess.run(
        ["just", "--justfile", str(root / "Justfile"), "--evaluate", "sase_core_dir"],
        cwd=root,
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
                "SASE_LINKED_REPO_SASE_CORE_DIR": "/tmp/real-linked-sase-core",
                "SASE_SIBLING_REPO_SASE_CORE_DIR": "/tmp/real-sibling-sase-core",
                "SASE_SIBLING_REPO_CORE_DIR": "/tmp/sibling-sase-core",
            },
            "/tmp/explicit-sase-core",
        ),
        (
            {
                "SASE_LINKED_REPO_SASE_CORE_DIR": "/tmp/real-linked-sase-core",
                "SASE_SIBLING_REPO_SASE_CORE_DIR": "/tmp/real-sibling-sase-core",
                "SASE_SIBLING_REPO_CORE_DIR": "/tmp/sibling-sase-core",
            },
            "/tmp/real-linked-sase-core",
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
    ],
)
def test_justfile_sase_core_dir_precedence(
    isolated_justfile_root: Path, env_vars: dict[str, str], expected: str
) -> None:
    workspace_core = isolated_justfile_root / "sase/repos/linked/sase-core"
    workspace_core.mkdir(parents=True)

    assert _evaluate_sase_core_dir(env_vars, root=isolated_justfile_root) == expected


def test_justfile_prefers_workspace_local_sase_core(
    isolated_justfile_root: Path,
) -> None:
    workspace_core = isolated_justfile_root / "sase/repos/linked/sase-core"
    workspace_core.mkdir(parents=True)

    assert (
        _evaluate_sase_core_dir({}, root=isolated_justfile_root)
        == "sase/repos/linked/sase-core"
    )


def test_justfile_preserves_sibling_sase_core_fallback(
    isolated_justfile_root: Path,
) -> None:
    assert _evaluate_sase_core_dir({}, root=isolated_justfile_root) == "../sase-core"


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
        "--no-sources $(just _core-overrides-arg) "
        '--reinstall-package mypy -e ".[dev]"'
    ) in output
    assert (
        output.count("/tmp/sase-custom-venv/bin/python tools/validate_test_environment")
        == 2
    )
    assert '--venv-dir "/tmp/sase-custom-venv"' in output
    assert 'check_core="--check-core"' in output
    assert "$check_core --check-editable --group dev" in output
    assert "--group visual" in output
    assert (
        "uv pip install --python /tmp/sase-custom-venv/bin/python "
        '--no-sources $(just _core-overrides-arg) -e ".[dev,visual]"'
    ) in output
