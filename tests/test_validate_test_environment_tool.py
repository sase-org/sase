from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any


import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/validate_test_environment"
FORCE_ENV = "SASE_TEST_SETUP_FORCE_REVALIDATE"
DEPENDENCY_GROUP_ERROR = 4


def _load_tool() -> dict[str, Any]:
    return runpy.run_path(str(SCRIPT), run_name="validate_test_environment")


def _fingerprint_environment(tmp_path: Path) -> dict[str, Path]:
    """A minimal set of real files for every identity input, under ``tmp_path``."""
    venv_dir = tmp_path / "venv"
    (venv_dir / "lib/python3.14/site-packages").mkdir(parents=True)
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    (venv_dir / "bin").mkdir()
    (venv_dir / "bin/python").write_bytes(b"fake-interpreter")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    uv_lock = tmp_path / "uv.lock"
    uv_lock.write_text("version = 1\n", encoding="utf-8")
    sase_core_dir = tmp_path / "sase-core"
    (sase_core_dir).mkdir()
    (sase_core_dir / "Cargo.toml").write_text(
        "[package]\nname = 'sase_core'\n", encoding="utf-8"
    )
    return {
        "venv_dir": venv_dir,
        "pyproject": pyproject,
        "uv_lock": uv_lock,
        "sase_core_dir": sase_core_dir,
    }


def _run_validator(
    *,
    venv_dir: Path,
    uv_lock: Path,
    cache_file: Path,
    group: str,
    force: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop(FORCE_ENV, None)
    if force:
        env[FORCE_ENV] = "1"
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--venv-dir",
            str(venv_dir),
            "--pyproject",
            str(ROOT / "pyproject.toml"),
            "--uv-lock",
            str(uv_lock),
            "--sase-core-dir",
            str(ROOT / "sase/repos/linked/sase-core"),
            "--cache-file",
            str(cache_file),
            "--group",
            group,
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _fake_venv(tmp_path: Path) -> Path:
    venv_dir = tmp_path / "venv"
    metadata_dir = venv_dir / "lib/python3.14/site-packages/demo-1.0.dist-info"
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "METADATA").write_text(
        "Name: demo\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    return venv_dir


def test_cached_verdict_skips_validator_until_lockfile_changes(tmp_path: Path) -> None:
    venv_dir = _fake_venv(tmp_path)
    uv_lock = tmp_path / "uv.lock"
    uv_lock.write_text("version = 1\n", encoding="utf-8")
    cache_file = tmp_path / "validation-cache.json"
    group = "definitely-missing-setup-cache-test-group"

    first = _run_validator(
        venv_dir=venv_dir,
        uv_lock=uv_lock,
        cache_file=cache_file,
        group=group,
    )
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    payload["verdicts"][f"dependency-group:{group}"]["stderr"] = (
        "cached dependency verdict\n"
    )
    cache_file.write_text(json.dumps(payload), encoding="utf-8")
    second = _run_validator(
        venv_dir=venv_dir,
        uv_lock=uv_lock,
        cache_file=cache_file,
        group=group,
    )
    uv_lock.write_text("version = 2\n", encoding="utf-8")
    invalidated = _run_validator(
        venv_dir=venv_dir,
        uv_lock=uv_lock,
        cache_file=cache_file,
        group=group,
    )

    assert first.returncode == DEPENDENCY_GROUP_ERROR
    assert "unknown dependency group" in first.stderr
    assert second.returncode == DEPENDENCY_GROUP_ERROR
    assert second.stderr == "cached dependency verdict\n"
    assert invalidated.returncode == DEPENDENCY_GROUP_ERROR
    assert "unknown dependency group" in invalidated.stderr


def test_venv_metadata_change_and_force_env_revalidate(tmp_path: Path) -> None:
    venv_dir = _fake_venv(tmp_path)
    metadata = next(venv_dir.glob("lib/python*/site-packages/*.dist-info/METADATA"))
    uv_lock = tmp_path / "uv.lock"
    uv_lock.write_text("version = 1\n", encoding="utf-8")
    cache_file = tmp_path / "validation-cache.json"
    group = "definitely-missing-setup-cache-test-group"

    first = _run_validator(
        venv_dir=venv_dir,
        uv_lock=uv_lock,
        cache_file=cache_file,
        group=group,
    )
    metadata.write_text("Name: demo\nVersion: 2.0\n", encoding="utf-8")
    metadata_invalidated = _run_validator(
        venv_dir=venv_dir,
        uv_lock=uv_lock,
        cache_file=cache_file,
        group=group,
    )
    cached = _run_validator(
        venv_dir=venv_dir,
        uv_lock=uv_lock,
        cache_file=cache_file,
        group=group,
    )
    forced = _run_validator(
        venv_dir=venv_dir,
        uv_lock=uv_lock,
        cache_file=cache_file,
        group=group,
        force=True,
    )

    assert first.returncode == DEPENDENCY_GROUP_ERROR
    assert "unknown dependency group" in metadata_invalidated.stderr
    assert "unknown dependency group" in cached.stderr
    assert forced.returncode == DEPENDENCY_GROUP_ERROR
    assert "unknown dependency group" in forced.stderr
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    assert (
        payload["verdicts"][f"dependency-group:{group}"]["code"]
        == DEPENDENCY_GROUP_ERROR
    )


def test_fingerprint_inputs_covers_every_escalating_bucket(tmp_path: Path) -> None:
    tool = _load_tool()
    env = _fingerprint_environment(tmp_path)

    inputs = tool["_fingerprint_inputs"](**env)

    assert {
        "pyproject",
        "uv-lock",
        "venv-config",
        "core-cargo",
        "validator:core-version",
        "validator:core-bindings",
        "validator:dependency-group",
        "validator:editable-metadata",
        "environment-metadata",
        "extension",
        "python",
    } <= set(inputs)


def test_fingerprint_inputs_are_independent_per_bucket(tmp_path: Path) -> None:
    tool = _load_tool()
    env = _fingerprint_environment(tmp_path)
    before = tool["_fingerprint_inputs"](**env)

    env["pyproject"].write_text("[project]\nname = 'demo-renamed'\n", encoding="utf-8")
    after = tool["_fingerprint_inputs"](**env)

    assert after["pyproject"] != before["pyproject"]
    for key in before:
        if key != "pyproject":
            assert after[key] == before[key]


def test_input_fingerprint_composite_still_reflects_every_bucket(
    tmp_path: Path,
) -> None:
    """The validator's own cache key must keep invalidating on any input change."""
    tool = _load_tool()
    env = _fingerprint_environment(tmp_path)
    before = tool["_input_fingerprint"](**env)

    env["uv_lock"].write_text("version = 2\n", encoding="utf-8")

    assert tool["_input_fingerprint"](**env) != before


def test_extension_fingerprint_finds_the_nested_extension(tmp_path: Path) -> None:
    """`sase_core_rs` installs to a nested package dir, not flat in site-packages."""
    tool = _load_tool()
    env = _fingerprint_environment(tmp_path)
    site_packages = env["venv_dir"] / "lib/python3.14/site-packages"
    empty = tool["_fingerprint_inputs"](**env)

    package_dir = site_packages / "sase_core_rs"
    package_dir.mkdir()
    (package_dir / "sase_core_rs.abi3.so").write_bytes(b"binary-v1")

    populated = tool["_fingerprint_inputs"](**env)

    assert populated["extension"] != empty["extension"]
    for key in empty:
        if key != "extension":
            assert populated[key] == empty[key]


def test_extension_fingerprint_is_content_based_not_stat_based(
    tmp_path: Path,
) -> None:
    """A rebuild that reproduces identical bytes must not read as a change."""
    tool = _load_tool()
    env = _fingerprint_environment(tmp_path)
    site_packages = env["venv_dir"] / "lib/python3.14/site-packages"
    package_dir = site_packages / "sase_core_rs"
    package_dir.mkdir()
    extension = package_dir / "sase_core_rs.abi3.so"
    extension.write_bytes(b"binary-v1")
    populated = tool["_fingerprint_inputs"](**env)

    os.utime(extension, (1_700_000_000, 1_700_000_000))
    touched = tool["_fingerprint_inputs"](**env)
    assert touched["extension"] == populated["extension"]

    extension.write_bytes(b"binary-v2")
    rebuilt = tool["_fingerprint_inputs"](**env)
    assert rebuilt["extension"] != populated["extension"]
