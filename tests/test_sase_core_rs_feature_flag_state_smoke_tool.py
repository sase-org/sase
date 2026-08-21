from __future__ import annotations

import importlib
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "smoke_sase_core_rs_feature_flag_state"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader(
        "sase_core_rs_feature_flag_state_smoke_tool",
        str(SCRIPT),
    )
    spec = importlib.util.spec_from_file_location(
        "sase_core_rs_feature_flag_state_smoke_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installed_core_feature_flag_state_round_trip() -> None:
    tool = _load_tool()
    module = importlib.import_module("sase_core_rs")

    assert tool.validate_round_trip(module) == {
        "empty_flags": {},
        "first_changed": True,
        "loaded_flags": {
            "epic_resume_gate": True,
            "prettier_enabled": False,
        },
        "idempotent_changed": False,
        "idempotent_previous": True,
    }


def test_feature_flag_state_smoke_requires_complete_binding_family() -> None:
    tool = _load_tool()

    with pytest.raises(
        RuntimeError,
        match=r"missing feature-flag state binding\(s\): "
        "feature_flag_state_get, feature_flag_state_set",
    ):
        tool.validate_round_trip(ModuleType("incomplete_sase_core_rs"))
