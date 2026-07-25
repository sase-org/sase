from __future__ import annotations

import importlib.util
import subprocess
import sys
import urllib.error
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "validate_sase_core_rs_version"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("validate_sase_core_rs_version_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "validate_sase_core_rs_version_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


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


class _Response:
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_published_minimum_validation_checks_exact_pypi_version(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.9.1,<0.10.0")
    seen: list[tuple[str, float]] = []

    def _urlopen(url: str, *, timeout: float) -> _Response:
        seen.append((url, timeout))
        return _Response()

    monkeypatch.setattr(tool.urllib.request, "urlopen", _urlopen)
    assert tool.main(["--pyproject", str(pyproject), "--published-minimum"]) == 0
    assert seen == [
        ("https://pypi.org/pypi/sase-core-rs/0.9.1/json", 5.0),
    ]


def test_published_minimum_cli_does_not_require_core_checkout(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.9.1,<0.10.0")
    monkeypatch.setattr(
        tool.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(),
    )

    assert (
        tool.main(
            [
                "--sase-core-dir",
                str(tmp_path / "missing-core"),
                "--pyproject",
                str(pyproject),
                "--published-minimum",
            ]
        )
        == 0
    )


def test_published_minimum_validation_rejects_unpublished_version(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.9.1,<0.10.0")

    def _urlopen(url: str, *, timeout: float) -> _Response:
        del timeout
        raise urllib.error.HTTPError(url, 404, "not found", {}, None)

    monkeypatch.setattr(tool.urllib.request, "urlopen", _urlopen)
    assert tool.main(["--pyproject", str(pyproject), "--published-minimum"]) == 1
    assert "sase-core-rs==0.9.1 is not published on PyPI" in capsys.readouterr().err


def test_published_minimum_validation_requires_inclusive_floor(
    tool: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>0.9.0,<0.10.0")

    assert tool.main(["--pyproject", str(pyproject), "--published-minimum"]) == 1
    assert "has no inclusive minimum" in capsys.readouterr().err
