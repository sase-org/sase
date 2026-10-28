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
    env.pop("SASE_CORE_WHEEL_CACHE_DIR", None)
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
        '--no-sources $(just --set venv_dir "/tmp/sase-custom-venv" '
        '--set sase_core_dir "/tmp/sase-custom-core" '
        "_core-overrides-arg) "
        '--reinstall-package mypy -e ".[dev]"'
    ) in output
    assert (
        output.count("/tmp/sase-custom-venv/bin/python tools/validate_test_environment")
        == 1
    )
    assert '--venv-dir "/tmp/sase-custom-venv"' in output
    assert 'check_core="--check-core"' in output
    assert "$check_core --check-editable --group dev" in output
    assert "--group visual" not in output
    assert '-e ".[dev,visual]"' not in output


def _run_core_overrides_arg(
    root: Path,
    *just_args: str,
    env_vars: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "just",
            "--justfile",
            str(root / "Justfile"),
            *just_args,
            "_core-overrides-arg",
        ],
        cwd=root,
        env=_clean_sase_core_env(env_vars or {}),
        check=True,
        capture_output=True,
        text=True,
    )


def _write_fake_core(root: Path, name: str = "opened-core") -> Path:
    core = root / name
    core.mkdir()
    (core / "Cargo.toml").write_text(
        '[package]\nname = "sase-core-fixture"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    return core


def _require_cargo() -> None:
    if shutil.which("cargo") is None:
        pytest.skip("cargo is required to emit source-path core overrides")


def test_core_overrides_are_enabled_for_prebuilt_wheel(
    isolated_justfile_root: Path,
) -> None:
    wheel = isolated_justfile_root / "sase_core_rs-test.whl"
    wheel.touch()
    (isolated_justfile_root / ".venv").mkdir()

    result = _run_core_overrides_arg(
        isolated_justfile_root,
        env_vars={"SASE_CORE_WHEEL": str(wheel)},
    )

    assert result.stdout.strip() == "--overrides .venv/sase-core-rs-overrides.txt"
    assert (isolated_justfile_root / ".venv/sase-core-rs-overrides.txt").read_text(
        encoding="utf-8"
    ) == "sase-core-rs\n"


def test_core_overrides_arg_writes_wheel_override_into_set_venv_dir(
    isolated_justfile_root: Path,
) -> None:
    wheel = isolated_justfile_root / "sase_core_rs-test.whl"
    wheel.touch()
    (isolated_justfile_root / "scratch-venv").mkdir()

    result = _run_core_overrides_arg(
        isolated_justfile_root,
        "--set",
        "venv_dir",
        "scratch-venv",
        env_vars={"SASE_CORE_WHEEL": str(wheel)},
    )

    assert (
        result.stdout.strip() == "--overrides scratch-venv/sase-core-rs-overrides.txt"
    )
    assert (
        isolated_justfile_root / "scratch-venv/sase-core-rs-overrides.txt"
    ).read_text(encoding="utf-8") == "sase-core-rs\n"
    assert not (isolated_justfile_root / ".venv/sase-core-rs-overrides.txt").exists()


def test_core_overrides_arg_emits_for_set_sase_core_dir(
    isolated_justfile_root: Path,
) -> None:
    _require_cargo()
    core = _write_fake_core(isolated_justfile_root)
    (isolated_justfile_root / "scratch-venv").mkdir()

    result = _run_core_overrides_arg(
        isolated_justfile_root,
        "--set",
        "venv_dir",
        "scratch-venv",
        "--set",
        "sase_core_dir",
        str(core),
    )
    bare = _run_core_overrides_arg(isolated_justfile_root)

    assert (
        result.stdout.strip() == "--overrides scratch-venv/sase-core-rs-overrides.txt"
    )
    assert (
        isolated_justfile_root / "scratch-venv/sase-core-rs-overrides.txt"
    ).read_text(encoding="utf-8") == "sase-core-rs\n"
    assert bare.stdout.strip() == ""
    assert not (isolated_justfile_root / ".venv/sase-core-rs-overrides.txt").exists()


def test_core_overrides_arg_emits_for_sase_core_dir_env(
    isolated_justfile_root: Path,
) -> None:
    _require_cargo()
    core = _write_fake_core(isolated_justfile_root)
    (isolated_justfile_root / ".venv").mkdir()

    result = _run_core_overrides_arg(
        isolated_justfile_root,
        env_vars={"SASE_CORE_DIR": str(core)},
    )

    assert result.stdout.strip() == "--overrides .venv/sase-core-rs-overrides.txt"
    assert (isolated_justfile_root / ".venv/sase-core-rs-overrides.txt").read_text(
        encoding="utf-8"
    ) == "sase-core-rs\n"


def test_core_overrides_arg_is_empty_without_local_core_or_wheel(
    isolated_justfile_root: Path,
) -> None:
    (isolated_justfile_root / ".venv").mkdir()

    result = _run_core_overrides_arg(isolated_justfile_root)

    assert result.stdout.strip() == ""
    assert not (isolated_justfile_root / ".venv/sase-core-rs-overrides.txt").exists()


def _forwarded_core_overrides_arg(venv_dir: str, sase_core_dir: str) -> str:
    return (
        f'just --set venv_dir "{venv_dir}" '
        f'--set sase_core_dir "{sase_core_dir}" '
        "_core-overrides-arg"
    )


@pytest.mark.parametrize(
    ("recipe", "venv_dir", "install_extra"),
    [
        ("install-venv", "/tmp/sase-custom-venv", '-e ".[dev]"'),
        ("_setup", "/tmp/sase-custom-venv", '--reinstall-package mypy -e ".[dev]"'),
        ("_setup-visual", "/tmp/sase-custom-venv", '-e ".[dev,visual]"'),
        (
            "_setup-terminal-smoke",
            "/tmp/sase-custom-venv",
            '-e ".[dev,terminal-smoke]"',
        ),
        ("_setup-demos", ".venv-demos", "-e ."),
    ],
)
def test_editable_reinstall_forwards_core_override_settings(
    recipe: str, venv_dir: str, install_extra: str
) -> None:
    result = subprocess.run(
        [
            "just",
            "--justfile",
            str(ROOT / "Justfile"),
            "--dry-run",
            "--set",
            "venv_dir",
            "/tmp/sase-custom-venv",
            "--set",
            "sase_core_dir",
            "/tmp/sase-custom-core",
            recipe,
        ],
        cwd=ROOT,
        env=_clean_sase_core_env({}),
        check=True,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    python_bin = f"{venv_dir}/bin/python"
    forwarded = _forwarded_core_overrides_arg(venv_dir, "/tmp/sase-custom-core")
    assert (
        f"uv pip install --python {python_bin} --no-sources $({forwarded}) "
        f"{install_extra}"
    ) in output
    assert "$(just _core-overrides-arg)" not in output


def test_every_nested_core_overrides_just_forwards_settings() -> None:
    justfile = (ROOT / "Justfile").read_text(encoding="utf-8")
    for line_no, line in enumerate(justfile.splitlines(), start=1):
        stripped = line.strip()
        if "_core-overrides-arg" not in stripped:
            continue
        if stripped.startswith("#") or stripped.startswith("_core-overrides-arg"):
            continue
        if "$(just" not in stripped:
            continue
        assert "--set venv_dir" in stripped, (
            f"Justfile:{line_no} nested _core-overrides-arg lost venv_dir: {stripped}"
        )
        assert "--set sase_core_dir" in stripped, (
            f"Justfile:{line_no} nested _core-overrides-arg lost sase_core_dir: "
            f"{stripped}"
        )


@pytest.mark.parametrize(
    "recipe",
    ["install-venv", "install-venv-visual", "install-venv-terminal-smoke", "_setup"],
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


def test_install_group_lists_venv_recipes_with_docs() -> None:
    result = subprocess.run(
        ["just", "--justfile", str(ROOT / "Justfile"), "--list"],
        cwd=ROOT,
        env=_clean_sase_core_env({}),
        check=True,
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert "[install]" in output
    assert "install-venv " in output
    assert "install-venv-visual" in output
    assert "install-venv-terminal-smoke" in output
    assert "Install the latest sase release from PyPI" in output
    assert "Install this checkout + its paired sase-core" in output
    assert "checkout's .venv" in output


def test_install_recipe_refuses_inside_agents() -> None:
    result = subprocess.run(
        ["just", "--justfile", str(ROOT / "Justfile"), "install", "-n"],
        cwd=ROOT,
        env=_clean_sase_core_env({"SASE_AGENT": "1"}),
        check=False,
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 2
    assert "won't run inside a SASE agent" in output
    assert "just install-venv" in output


def test_install_dev_recipe_refuses_inside_agents() -> None:
    result = subprocess.run(
        ["just", "--justfile", str(ROOT / "Justfile"), "install-dev", "-n"],
        cwd=ROOT,
        env=_clean_sase_core_env({"SASE_AGENT": "1"}),
        check=False,
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 2
    assert "won't run inside a SASE agent" in output
    assert "just install-venv" in output


def test_install_dev_recipe_help_lists_dev_options() -> None:
    result = subprocess.run(
        ["just", "--justfile", str(ROOT / "Justfile"), "install-dev", "--help"],
        cwd=ROOT,
        env=_clean_sase_core_env({}),
        check=False,
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0
    assert "Install this checkout plus its paired sase-core" in output
    assert "--sync" in output


def test_install_recipe_help_lists_pypi_options() -> None:
    result = subprocess.run(
        ["just", "--justfile", str(ROOT / "Justfile"), "install", "--help"],
        cwd=ROOT,
        env=_clean_sase_core_env({}),
        check=False,
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0
    assert "Install the latest sase release from PyPI" in output
    assert "--version X" in output
