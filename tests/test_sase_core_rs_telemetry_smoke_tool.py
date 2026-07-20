from __future__ import annotations

import importlib
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "smoke_sase_core_rs_telemetry"


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


def test_declared_minimum_tracks_pyproject_dependency() -> None:
    tool = _load_tool()

    assert tool.declared_minimum_version(ROOT / "pyproject.toml") == "0.10.0"


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
