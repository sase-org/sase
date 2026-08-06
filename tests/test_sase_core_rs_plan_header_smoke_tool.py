from __future__ import annotations

import importlib
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "smoke_sase_core_rs_plan_header"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("sase_core_rs_plan_header_smoke_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "sase_core_rs_plan_header_smoke_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installed_core_plan_header_round_trip() -> None:
    tool = _load_tool()
    module = importlib.import_module("sase_core_rs")

    assert tool.validate_round_trip(module) == {
        "schema_version": 3,
        "disposition": "canonical",
        "section_kinds": ["PROMPT", "BEAD", "ARTIFACTS", "COMMITS"],
        "mutation_round_trip": True,
        "unlinked_bead": True,
        "cross_repo_prompt": True,
        "artifacts_section": True,
        "fenced_examples_ignored": True,
        "legacy_parent_removed": True,
    }


def test_plan_header_smoke_requires_complete_binding_family() -> None:
    tool = _load_tool()

    with pytest.raises(
        RuntimeError,
        match=r"missing plan-header binding\(s\): "
        "sdd_plan_header_block_wire_schema_version",
    ):
        tool.validate_round_trip(ModuleType("incomplete_sase_core_rs"))
