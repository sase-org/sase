from __future__ import annotations

import importlib
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "smoke_sase_core_rs_glossary_line_break"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader(
        "sase_core_rs_glossary_line_break_smoke_tool", str(SCRIPT)
    )
    spec = importlib.util.spec_from_file_location(
        "sase_core_rs_glossary_line_break_smoke_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installed_core_glossary_line_break_matching() -> None:
    tool = _load_tool()
    module = importlib.import_module("sase_core_rs")

    assert tool.validate_line_break_matching(module) == {
        "term": "Xprompt Memory",
        "matched_text": "xprompt\n  memory",
        "segment_count": 2,
        "segment_ranges": [
            {
                "start": {"line": 0, "character": 4},
                "end": {"line": 0, "character": 11},
            },
            {
                "start": {"line": 1, "character": 2},
                "end": {"line": 1, "character": 8},
            },
        ],
        "blank_line_rejected": True,
    }


def test_glossary_line_break_smoke_requires_compile_binding() -> None:
    tool = _load_tool()

    with pytest.raises(
        RuntimeError,
        match=r"missing glossary line-break binding\(s\): compile_glossary_catalog",
    ):
        tool.validate_line_break_matching(ModuleType("incomplete_sase_core_rs"))
