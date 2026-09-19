from __future__ import annotations

import importlib
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "smoke_sase_tool_runs"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("sase_tool_runs_smoke_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "sase_tool_runs_smoke_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tool_runs_harness_marks_public_commands_phase_pending() -> None:
    module = importlib.import_module("sase_core_rs")
    if not hasattr(module, "tool_run_begin"):
        pytest.skip("tool_run bindings are not in this wheel")
    tool = _load_tool()
    sase = ROOT / ".venv" / "bin" / "sase"
    report = tool.run_harness(
        sase=str(sase) if sase.exists() else "sase",
        live=False,
        keep=False,
    )
    statuses = {case["id"]: case["status"] for case in report["cases"]}
    assert statuses["core-ledger-round-trip"] == "pass"
    assert statuses["dod-2-exact-execution"] == "phase-pending"
    assert report["failed"] == 0
