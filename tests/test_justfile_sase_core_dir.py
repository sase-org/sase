from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._test_selection_manifest import sase_core_directory


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]


def _clean_sase_core_env(env_vars: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("SASE_CORE_DIR", None)
    env.pop("SASE_CORE_WHEEL", None)
    env.pop("SASE_ALLOW_STALE_CORE", None)
    env.pop("SASE_LINKED_REPO_SASE_CORE_DIR", None)
    env.pop("SASE_LINKED_REPO_SASE_CORE_PRIMARY_DIR", None)
    env.pop("SASE_SIBLING_REPO_SASE_CORE_DIR", None)
    env.pop("SASE_SIBLING_REPO_SASE_CORE_PRIMARY_DIR", None)
    env.pop("SASE_SIBLING_REPO_CORE_DIR", None)
    env.pop("SASE_SIBLING_REPO_CORE_PRIMARY_DIR", None)
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


def test_justfile_sase_core_dir_prefers_explicit_override(
    isolated_justfile_root: Path,
) -> None:
    workspace_core = isolated_justfile_root / "sase/repos/linked/sase-core"
    workspace_core.mkdir(parents=True)

    assert (
        _evaluate_sase_core_dir(
            {
                "SASE_CORE_DIR": "/tmp/explicit-sase-core",
                "SASE_LINKED_REPO_SASE_CORE_DIR": str(workspace_core),
                "SASE_LINKED_REPO_SASE_CORE_PRIMARY_DIR": "/tmp/primary-sase-core",
            },
            root=isolated_justfile_root,
        )
        == "/tmp/explicit-sase-core"
    )


@pytest.mark.parametrize(
    "env_name",
    [
        "SASE_LINKED_REPO_SASE_CORE_DIR",
        "SASE_SIBLING_REPO_SASE_CORE_DIR",
        "SASE_SIBLING_REPO_CORE_DIR",
    ],
)
def test_justfile_sase_core_dir_accepts_current_workspace_env(
    isolated_justfile_root: Path, env_name: str
) -> None:
    workspace_core = isolated_justfile_root / "sase/repos/linked/sase-core"
    workspace_core.mkdir(parents=True)

    assert _evaluate_sase_core_dir(
        {
            env_name: str(workspace_core),
            "SASE_LINKED_REPO_SASE_CORE_PRIMARY_DIR": "/tmp/primary-sase-core",
        },
        root=isolated_justfile_root,
    ) == str(workspace_core)


def test_justfile_sase_core_dir_uses_primary_for_stale_agent_workspace_env(
    isolated_justfile_root: Path,
) -> None:
    foreign_core = isolated_justfile_root.parent / "sase_11/sase/repos/linked/sase-core"
    primary_core = isolated_justfile_root.parent / "primary-sase-core"

    assert _evaluate_sase_core_dir(
        {
            "SASE_LINKED_REPO_SASE_CORE_DIR": str(foreign_core),
            "SASE_SIBLING_REPO_SASE_CORE_DIR": str(foreign_core),
            "SASE_SIBLING_REPO_CORE_DIR": str(foreign_core),
            "SASE_LINKED_REPO_SASE_CORE_PRIMARY_DIR": str(primary_core),
            "SASE_SIBLING_REPO_SASE_CORE_PRIMARY_DIR": "/tmp/sibling-primary",
            "SASE_SIBLING_REPO_CORE_PRIMARY_DIR": "/tmp/legacy-primary",
        },
        root=isolated_justfile_root,
    ) == str(primary_core)


def test_selection_manifest_core_dir_mirrors_stale_env_resolution(
    isolated_justfile_root: Path,
) -> None:
    foreign_core = isolated_justfile_root.parent / "sase_11/sase/repos/linked/sase-core"
    primary_core = isolated_justfile_root.parent / "primary-sase-core"

    assert (
        sase_core_directory(
            isolated_justfile_root,
            {
                "SASE_LINKED_REPO_SASE_CORE_DIR": str(foreign_core),
                "SASE_LINKED_REPO_SASE_CORE_PRIMARY_DIR": str(primary_core),
            },
        )
        == primary_core
    )


def test_justfile_sase_core_dir_ignores_stale_env_without_primary(
    isolated_justfile_root: Path,
) -> None:
    workspace_core = isolated_justfile_root / "sase/repos/linked/sase-core"
    workspace_core.mkdir(parents=True)
    foreign_core = isolated_justfile_root.parent / "sase_11/sase/repos/linked/sase-core"

    assert (
        _evaluate_sase_core_dir(
            {"SASE_LINKED_REPO_SASE_CORE_DIR": str(foreign_core)},
            root=isolated_justfile_root,
        )
        == "sase/repos/linked/sase-core"
    )


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
            "tests/test_run_pytest_command.py",
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


def test_core_overrides_are_enabled_for_prebuilt_wheel(
    isolated_justfile_root: Path,
) -> None:
    wheel = isolated_justfile_root / "sase_core_rs-test.whl"
    wheel.touch()
    (isolated_justfile_root / ".venv").mkdir()

    result = subprocess.run(
        [
            "just",
            "--justfile",
            str(isolated_justfile_root / "Justfile"),
            "_core-overrides-arg",
        ],
        cwd=isolated_justfile_root,
        env=_clean_sase_core_env({"SASE_CORE_WHEEL": str(wheel)}),
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "--overrides .venv/sase-core-rs-overrides.txt"
    assert (isolated_justfile_root / ".venv/sase-core-rs-overrides.txt").read_text(
        encoding="utf-8"
    ) == "sase-core-rs\n"


@pytest.mark.parametrize(
    "recipe",
    ["install", "install-visual", "install-terminal-smoke", "_setup"],
)
def test_prebuilt_wheel_install_path_is_present(recipe: str) -> None:
    result = subprocess.run(
        ["just", "--justfile", str(ROOT / "Justfile"), "--dry-run", recipe],
        cwd=ROOT,
        env=_clean_sase_core_env({"SASE_CORE_WHEEL": "/tmp/sase-core.whl"}),
        check=True,
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert 'if [ -n "${SASE_CORE_WHEEL:-}" ]; then' in output
    assert 'uv pip install --python .venv/bin/python "$SASE_CORE_WHEEL"' in output
