from __future__ import annotations

import importlib
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "smoke_sase_core_rs_tool_runs"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("sase_core_rs_tool_runs_smoke_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "sase_core_rs_tool_runs_smoke_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installed_core_tool_runs_round_trip() -> None:
    module = importlib.import_module("sase_core_rs")
    if not hasattr(module, "tool_run_begin"):
        pytest.skip("tool_run bindings are not in this wheel")
    tool = _load_tool()
    result = tool.validate_round_trip(module)
    assert result["schema_version"] == 1
    assert result["run_state"] == "succeeded"
    assert result["run_count"] == 1
    assert result["typical_duration_ms"] == 12
    assert result["unknown_complete"] is False
