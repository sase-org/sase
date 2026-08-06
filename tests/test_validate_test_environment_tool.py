from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/validate_test_environment"
FORCE_ENV = "SASE_TEST_SETUP_FORCE_REVALIDATE"
DEPENDENCY_GROUP_ERROR = 4


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
