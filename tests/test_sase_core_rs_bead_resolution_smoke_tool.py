from __future__ import annotations

import importlib
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "smoke_sase_core_rs_bead_resolution"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("sase_core_rs_bead_resolution_smoke_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "sase_core_rs_bead_resolution_smoke_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installed_core_typed_resolution_round_trip() -> None:
    tool = _load_tool()
    module = importlib.import_module("sase_core_rs")

    assert tool.validate_round_trip(module) == {
        "issue_id": "smoke-1",
        "returned_resolution": "canceled",
        "persisted_resolution": "canceled",
    }
