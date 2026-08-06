from __future__ import annotations

import importlib
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "smoke_sase_core_rs_at_reference_file_gate"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader(
        "sase_core_rs_at_reference_file_gate_smoke_tool",
        str(SCRIPT),
    )
    spec = importlib.util.spec_from_file_location(
        "sase_core_rs_at_reference_file_gate_smoke_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installed_core_at_reference_file_gate() -> None:
    tool = _load_tool()
    module = importlib.import_module("sase_core_rs")

    assert tool.validate_file_gate(module) == {
        "default_groups": ["artifact"],
        "default_files_suppressed": True,
        "revealed_groups": ["artifact", "file"],
        "kind_miss_groups": ["file"],
    }


def test_at_reference_file_gate_smoke_requires_complete_binding_family() -> None:
    tool = _load_tool()

    with pytest.raises(
        RuntimeError,
        match=r"missing at-reference binding\(s\): "
        "at_reference_context, at_reference_menu",
    ):
        tool.validate_file_gate(ModuleType("incomplete_sase_core_rs"))
