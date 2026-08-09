from __future__ import annotations

import importlib
import importlib.util
import re
import tomllib
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "smoke_sase_core_rs_telemetry"
DEPENDENCY_NAME = "sase-core-rs"
PACKAGE_NAME_RE = re.compile(r"\s*([A-Za-z0-9_.-]+)")
INCLUSIVE_MINIMUM_RE = re.compile(r"(?:^|,)\s*>=\s*([^,;\s]+)")


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("sase_core_rs_telemetry_smoke_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "sase_core_rs_telemetry_smoke_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _declared_core_floor(pyproject: Path) -> str:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dependencies = data["project"]["dependencies"]
    assert isinstance(dependencies, list)

    for dependency in dependencies:
        assert isinstance(dependency, str)
        requirement = dependency.split(";", 1)[0].strip()
        name_match = PACKAGE_NAME_RE.match(requirement)
        assert name_match is not None
        normalized = name_match.group(1).lower().replace("_", "-")
        if normalized != DEPENDENCY_NAME:
            continue
        match = INCLUSIVE_MINIMUM_RE.search(requirement[name_match.end() :])
        assert match is not None
        return match.group(1)

    raise AssertionError(f"{DEPENDENCY_NAME} dependency is missing")


def test_declared_minimum_tracks_pyproject_dependency() -> None:
    tool = _load_tool()

    pyproject = ROOT / "pyproject.toml"
    assert tool.declared_minimum_version(pyproject) == _declared_core_floor(pyproject)


def test_declared_minimum_parses_inclusive_floor(tmp_path: Path) -> None:
    tool = _load_tool()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\ndependencies = ["sase-core-rs>=0.7.2,<0.8.0"]\n',
        encoding="utf-8",
    )

    assert tool.declared_minimum_version(pyproject) == "0.7.2"


def test_declared_minimum_requires_inclusive_floor(tmp_path: Path) -> None:
    tool = _load_tool()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\ndependencies = ["sase-core-rs<0.7.0"]\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no inclusive minimum"):
        tool.declared_minimum_version(pyproject)


def test_installed_core_telemetry_round_trip() -> None:
    tool = _load_tool()
    module = importlib.import_module("sase_core_rs")

    assert tool.validate_round_trip(module) == {
        "samples_recorded": 1,
        "instant_value": 3.0,
        "range_value": 3.0,
        "raw_rows_folded": 1,
        "raw_sample_count": 0,
        "rollup_5m_count": 1,
    }
