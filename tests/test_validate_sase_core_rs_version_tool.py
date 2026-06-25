from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "validate_sase_core_rs_version"


def _write_core(root: Path, version: str = "0.2.0") -> Path:
    core = root / "sase-core"
    core.mkdir()
    (core / "Cargo.toml").write_text(
        f"""
[workspace]
members = []

[workspace.package]
version = "{version}"
""".lstrip(),
        encoding="utf-8",
    )
    return core


def _write_pyproject(
    root: Path,
    dependency: str = "sase-core-rs>=0.2.0,<0.3.0",
) -> Path:
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        f"""
[project]
dependencies = [
    "{dependency}",
]
""".lstrip(),
        encoding="utf-8",
    )
    return pyproject


def _run_validator(core: Path, pyproject: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--sase-core-dir",
            str(core),
            "--pyproject",
            str(pyproject),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_sase_core_rs_version_validation_passes_when_source_is_in_range(
    tmp_path: Path,
) -> None:
    core = _write_core(tmp_path, "0.2.0")
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.2.0,<0.3.0")

    result = _run_validator(core, pyproject)

    assert result.returncode == 0
    assert result.stderr == ""


def test_sase_core_rs_version_validation_fails_when_source_is_behind(
    tmp_path: Path,
) -> None:
    core = _write_core(tmp_path, "0.1.4")
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.2.0,<0.3.0")

    result = _run_validator(core, pyproject)

    assert result.returncode == 1
    assert "sase-core checkout is behind" in result.stderr
    assert "source version 0.1.4" in result.stderr
    assert "sase-core-rs>=0.2.0,<0.3.0" in result.stderr
    assert "Pull/rebuild `sase-core`" in result.stderr


def test_sase_core_rs_version_validation_fails_when_source_hits_upper_bound(
    tmp_path: Path,
) -> None:
    core = _write_core(tmp_path, "0.3.0")
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.2.0,<0.3.0")

    result = _run_validator(core, pyproject)

    assert result.returncode == 1
    assert "ahead of sase's compatibility window" in result.stderr
    assert "source version 0.3.0" in result.stderr
    assert "Bump `sase`'s `sase-core-rs` constraint" in result.stderr


def test_sase_core_rs_version_validation_reports_missing_cargo_toml(
    tmp_path: Path,
) -> None:
    core = tmp_path / "sase-core"
    core.mkdir()
    pyproject = _write_pyproject(tmp_path)

    result = _run_validator(core, pyproject)

    assert result.returncode == 1
    assert "missing TOML file" in result.stderr
    assert "Cargo.toml" in result.stderr


def test_sase_core_rs_version_validation_reports_missing_dependency(
    tmp_path: Path,
) -> None:
    core = _write_core(tmp_path)
    pyproject = _write_pyproject(tmp_path, "jinja2")

    result = _run_validator(core, pyproject)

    assert result.returncode == 1
    assert "does not declare a sase-core-rs dependency" in result.stderr


def test_sase_core_rs_version_validation_reports_malformed_specifier(
    tmp_path: Path,
) -> None:
    core = _write_core(tmp_path)
    pyproject = _write_pyproject(tmp_path, "sase-core-rs~=0.2")

    result = _run_validator(core, pyproject)

    assert result.returncode == 1
    assert "unsupported sase-core-rs specifier" in result.stderr


def test_sase_core_rs_version_validation_reports_malformed_source_version(
    tmp_path: Path,
) -> None:
    core = _write_core(tmp_path, "next")
    pyproject = _write_pyproject(tmp_path)

    result = _run_validator(core, pyproject)

    assert result.returncode == 1
    assert "unsupported Cargo workspace version" in result.stderr
