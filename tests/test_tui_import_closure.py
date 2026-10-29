"""Tests for tools/tui_import_closure first-party reporting."""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "tui_import_closure"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("tui_import_closure_tool", str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "tui_import_closure_tool", TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_is_first_party_module() -> None:
    tool = _load_tool()
    assert tool.is_first_party_module("sase") is True
    assert tool.is_first_party_module("sase.ace.tui.app") is True
    assert tool.is_first_party_module("sase_core") is False
    assert tool.is_first_party_module("sase_core_rs") is False
    assert tool.is_first_party_module("textual") is False
    assert tool.is_first_party_module("sys") is False


def test_format_current_line_reports_first_party_count() -> None:
    tool = _load_tool()
    measurement = tool.ClosureMeasurement(
        elapsed_seconds=1.25,
        module_count=3549,
        sase_modules=("sase", "sase.ace.tui.app"),
    )
    assert tool.format_current_line(measurement) == (
        "TUI app import closure: 2 sase.* modules (3549 total, 1.25s CPU)"
    )


def test_format_diff_lines_report_first_party_delta() -> None:
    tool = _load_tool()
    base = tool.ClosureMeasurement(
        elapsed_seconds=1.0,
        module_count=3540,
        sase_modules=("sase", "sase.ace.tui.app"),
    )
    current = tool.ClosureMeasurement(
        elapsed_seconds=1.1,
        module_count=3550,
        sase_modules=("sase", "sase.ace.tui.app", "sase.ace.tui.new"),
    )
    lines = tool.format_diff_lines(
        current, base, rev="origin/master", sha="0123456789abcdef"
    )
    assert lines[0] == "at origin/master (0123456789ab): 2 sase.* modules (3540 total)"
    assert lines[1] == "change: +1 sase.* modules (+10 total)"
    assert "added (1):" in lines
    assert "  +sase.ace.tui.new" in lines


def test_format_diff_lines_total_only_growth_is_not_first_party_change() -> None:
    tool = _load_tool()
    modules = ("sase", "sase.ace.tui.app")
    base = tool.ClosureMeasurement(
        elapsed_seconds=1.0, module_count=3540, sase_modules=modules
    )
    current = tool.ClosureMeasurement(
        elapsed_seconds=1.0, module_count=3555, sase_modules=modules
    )
    lines = tool.format_diff_lines(current, base, rev="HEAD", sha="abc123def456")
    assert lines[1] == "change: +0 sase.* modules (+15 total)"
    assert lines[-1] == "no sase.* module changes"


def test_main_prints_first_party_count(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _load_tool()
    current = tool.ClosureMeasurement(
        elapsed_seconds=0.5,
        module_count=3549,
        sase_modules=("sase", "sase.ace"),
    )
    monkeypatch.setattr(tool, "_measure", lambda cwd: current)
    assert tool.main([]) == 0
    out = capsys.readouterr().out
    assert "TUI app import closure: 2 sase.* modules (3549 total, 0.50s CPU)" in out
