"""Tests for the `tools/print_scoped_summary` CLI wrapper.

`just check` wraps `test-scoped` in `tools/run_silent`, which discards
captured stdout+stderr on success. This tool is the separate `check` step
that runs right after `run_silent` returns, reading the selection manifest
`test-scoped` just finished writing so the scoped lane's summary survives the
success path.
"""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

from tests._test_selection_manifest import (
    MANIFEST_FILENAME,
    SELECTION_DIRECTORY,
    write_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "print_scoped_summary"


def _load_tool(repo_root: Path) -> ModuleType:
    loader = SourceFileLoader("print_scoped_summary_tool", str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "print_scoped_summary_tool", TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REPO_ROOT = repo_root
    return module


@pytest.fixture
def tool(tmp_path: Path) -> ModuleType:
    return _load_tool(tmp_path)


def test_tool_script_is_executable() -> None:
    assert TOOL_PATH.exists()
    assert TOOL_PATH.stat().st_mode & 0o111


def test_prints_nothing_when_no_manifest_exists(
    tool: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert tool.main() == 0

    assert capsys.readouterr().out == ""


def test_prints_the_scoped_summary_from_the_persisted_manifest(
    tool: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_manifest(
        tmp_path / SELECTION_DIRECTORY / MANIFEST_FILENAME,
        {
            "escalated": False,
            "selected_count": 3,
            "universe_count": 12,
            "rules_fired": [],
            "outcome": "passed",
        },
    )

    assert tool.main() == 0

    out = capsys.readouterr().out
    assert (
        out.strip()
        == "scoped: selected 3 of 12 test files (25.0%; rules: none); contexts baseline missing"
    )


def test_reports_escalation_from_the_persisted_manifest(
    tool: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_manifest(
        tmp_path / SELECTION_DIRECTORY / MANIFEST_FILENAME,
        {
            "escalated": True,
            "selected_count": 0,
            "universe_count": 12,
            "rules_fired": ["justfile"],
            "outcome": "escalated",
        },
    )

    assert tool.main() == 0

    assert "escalated to the full suite" in capsys.readouterr().out
