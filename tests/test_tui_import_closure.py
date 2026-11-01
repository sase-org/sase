"""Tests for tools/tui_import_closure first-party and footprint reporting."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

from tests._tui_import_fixtures import (
    MONOLITH_FILES,
    SPLIT_FILES,
    footprint,
    implementation,
    measure_package,
    with_eager_import,
    write_files,
)


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


def _measurement(
    modules: Mapping[str, int],
    *,
    elapsed: float = 1.0,
    total: int = 3549,
) -> footprint.ImportMeasurement:
    """A measurement with the given first-party modules and their footprints."""
    return footprint.ImportMeasurement(
        elapsed_seconds=elapsed,
        module_count=total,
        first_party_modules=tuple(sorted(modules)),
        deferred_modules=(),
        footprint=footprint.SourceFootprint(
            total_bytes=sum(modules.values()), module_bytes=dict(modules)
        ),
    )


def test_is_first_party_module() -> None:
    tool = _load_tool()
    assert tool.is_first_party_module("sase") is True
    assert tool.is_first_party_module("sase.ace.tui.app") is True
    assert tool.is_first_party_module("sase_core") is False
    assert tool.is_first_party_module("sase_core_rs") is False
    assert tool.is_first_party_module("textual") is False
    assert tool.is_first_party_module("sys") is False


def test_format_current_line_reports_count_footprint_and_cpu() -> None:
    tool = _load_tool()
    measurement = _measurement(
        {"sase": 0, "sase.ace.tui.app": 12_345_678}, elapsed=1.25
    )
    assert tool.format_current_line(measurement) == (
        "TUI app import closure: 2 sase.* modules (3549 total, 1.25s CPU), "
        "footprint 12,345,678 bytes"
    )


def test_format_diff_lines_report_signed_footprint_and_module_delta() -> None:
    tool = _load_tool()
    base = _measurement({"sase": 0, "sase.ace.tui.app": 100}, total=3540)
    current = _measurement(
        {"sase": 0, "sase.ace.tui.app": 100, "sase.ace.tui.new": 250}, total=3550
    )
    lines = tool.format_diff_lines(
        current, base, rev="origin/master", sha="0123456789abcdef"
    )
    assert lines[0] == (
        "at origin/master (0123456789ab): 2 sase.* modules (3540 total), "
        "footprint 100 bytes"
    )
    assert lines[1] == "change: +1 sase.* modules (+10 total), footprint +250 bytes"
    assert "footprint contributors (1, largest first):" in lines
    assert "  +250 sase.ace.tui.new (added)" in lines
    assert "added (1):" in lines
    assert "  +sase.ace.tui.new" in lines


def test_format_diff_lines_name_growth_inside_an_existing_module() -> None:
    tool = _load_tool()
    base = _measurement({"sase": 0, "sase.a": 1_000, "sase.b": 500})
    current = _measurement({"sase": 0, "sase.a": 1_288, "sase.b": 500})
    lines = tool.format_diff_lines(current, base, rev="HEAD", sha="abc123def456")
    assert lines[1] == "change: +0 sase.* modules (+0 total), footprint +288 bytes"
    assert "  +288 sase.a (changed: 1,000 -> 1,288)" in lines
    assert not any("sase.b" in line for line in lines)
    assert lines[-1] == "no sase.* module changes"


def test_format_diff_lines_list_added_removed_and_changed_by_size() -> None:
    tool = _load_tool()
    base = _measurement({"sase": 0, "sase.old": 700, "sase.kept": 90})
    current = _measurement({"sase": 0, "sase.new": 40, "sase.kept": 100})
    lines = tool.format_diff_lines(current, base, rev="HEAD", sha="abc123def456")
    contributors = lines[lines.index("footprint contributors (3, largest first):") :]
    assert contributors[1:4] == [
        "  -700 sase.old (removed)",
        "  +40 sase.new (added)",
        "  +10 sase.kept (changed: 90 -> 100)",
    ]
    assert "added (1):" in lines
    assert "  +sase.new" in lines
    assert "removed (1):" in lines
    assert "  -sase.old" in lines
    assert lines[1] == "change: +0 sase.* modules (+0 total), footprint -650 bytes"


def test_format_diff_lines_higher_module_count_with_unchanged_footprint() -> None:
    tool = _load_tool()
    base = _measurement({"sase": 0, "sase.big": 900}, total=3540)
    current = _measurement(
        {"sase": 0, "sase.big": 900, "sase.big._a": 0, "sase.big._b": 0}, total=3542
    )
    lines = tool.format_diff_lines(current, base, rev="HEAD", sha="abc123def456")
    assert lines[1] == "change: +2 sase.* modules (+2 total), footprint +0 bytes"
    assert "no source footprint changes" in lines
    assert not any(line.startswith("footprint contributors") for line in lines)
    assert "added (2):" in lines


def test_format_diff_lines_total_only_growth_is_not_a_closure_change() -> None:
    tool = _load_tool()
    modules = {"sase": 0, "sase.ace.tui.app": 10}
    base = _measurement(modules, total=3540)
    current = _measurement(modules, total=3555)
    lines = tool.format_diff_lines(current, base, rev="HEAD", sha="abc123def456")
    assert lines[1] == "change: +0 sase.* modules (+15 total), footprint +0 bytes"
    assert lines[-1] == "no sase.* module changes"


def test_diff_of_a_real_mechanical_split_reports_no_footprint_change(
    tmp_path: Path,
) -> None:
    tool = _load_tool()
    monolith_root = tmp_path / "monolith"
    split_root = tmp_path / "split"
    write_files(monolith_root, MONOLITH_FILES)
    write_files(split_root, SPLIT_FILES)
    base = measure_package(monolith_root)
    current = measure_package(split_root)

    lines = tool.format_diff_lines(current, base, rev="HEAD", sha="abc123def456")
    assert lines[1].endswith("footprint +0 bytes")
    # The code moved from the monolith into the helpers, net zero.
    assert any(line.startswith("footprint unchanged overall;") for line in lines)
    assert not any(line.startswith("footprint contributors") for line in lines)
    assert any("budgetpkg._alpha (added)" in line for line in lines)
    assert any("budgetpkg.app (changed:" in line for line in lines)
    assert "added (2):" in lines


def test_diff_of_real_eager_growth_names_the_responsible_source(
    tmp_path: Path,
) -> None:
    tool = _load_tool()
    base_root = tmp_path / "base"
    grown_root = tmp_path / "grown"
    write_files(base_root, MONOLITH_FILES)
    write_files(
        grown_root,
        {
            **with_eager_import(MONOLITH_FILES, "extra"),
            "budgetpkg/extra.py": implementation(3),
        },
    )
    base = measure_package(base_root)
    current = measure_package(grown_root)

    lines = tool.format_diff_lines(current, base, rev="HEAD", sha="abc123def456")
    added = current.footprint.module_bytes["budgetpkg.extra"]
    assert f"  +{added:,} budgetpkg.extra (added)" in lines
    # The monolith's own unchanged source is not blamed.
    assert not any("budgetpkg.app (" in line for line in lines)


def test_measure_reports_import_and_source_failures_as_exit_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _load_tool()

    def _probe_fails(*_args: object, **_kwargs: object) -> object:
        raise footprint.ImportProbeError("import of sase.ace.tui.app failed:\nboom")

    monkeypatch.setattr(tool.footprint, "measure_import", _probe_fails)
    with pytest.raises(
        SystemExit, match=r"(?s)TUI app measurement failed: import of sase.ace.*boom"
    ):
        tool._measure(ROOT)

    def _source_missing(*_args: object, **_kwargs: object) -> object:
        raise footprint.FootprintError("cannot measure 'sase.x': source is gone")

    monkeypatch.setattr(tool.footprint, "measure_import", _source_missing)
    with pytest.raises(SystemExit, match="cannot measure 'sase.x'"):
        tool._measure(ROOT)


def test_main_prints_first_party_count_and_footprint(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _load_tool()
    current = _measurement({"sase": 0, "sase.ace": 4_200}, elapsed=0.5)
    monkeypatch.setattr(tool, "_measure", lambda cwd, **kwargs: current)
    assert tool.main([]) == 0
    out = capsys.readouterr().out
    assert (
        "TUI app import closure: 2 sase.* modules (3549 total, 0.50s CPU), "
        "footprint 4,200 bytes"
    ) in out
