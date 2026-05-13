from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def _load_run_pytest() -> ModuleType:
    loader = SourceFileLoader("run_pytest_tool", str(ROOT / "tools" / "run_pytest"))
    spec = importlib.util.spec_from_file_location(
        "run_pytest_tool", ROOT / "tools" / "run_pytest", loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalizes_invocation_relative_file_selector() -> None:
    runner = _load_run_pytest()

    result = runner._normalize_args(["test_repeat_launcher.py"], ROOT / "tests")

    assert result == ["tests/test_repeat_launcher.py"]


def test_normalizes_invocation_relative_node_selector() -> None:
    runner = _load_run_pytest()

    result = runner._normalize_args(
        [
            "test_repeat_launcher.py::TestExtractRepeatAndName::test_parses_repeat_and_name"
        ],
        ROOT / "tests",
    )

    assert result == [
        "tests/test_repeat_launcher.py::TestExtractRepeatAndName::test_parses_repeat_and_name"
    ]


def test_preserves_repo_relative_selector() -> None:
    runner = _load_run_pytest()

    result = runner._normalize_args(["tests/test_repeat_launcher.py"], ROOT / "tests")

    assert result == ["tests/test_repeat_launcher.py"]


def test_strips_just_separator_and_preserves_keyword_expression() -> None:
    runner = _load_run_pytest()

    result = runner._normalize_args(
        ["--", "-k", "test_repeat_launcher.py", "test_repeat_launcher.py"],
        ROOT / "tests",
    )

    assert result == [
        "-k",
        "test_repeat_launcher.py",
        "tests/test_repeat_launcher.py",
    ]


def test_visual_mode_selects_visual_marker() -> None:
    runner = _load_run_pytest()

    result = runner._pytest_command("visual", ["tests/ace/tui/visual"])

    assert result[0:3] == [runner.sys.executable, "-m", "pytest"]
    assert result[-3:] == ["-m", "visual", "tests/ace/tui/visual"]


def test_visual_flag_selects_visual_mode() -> None:
    runner = _load_run_pytest()

    mode, args = runner._resolve_mode_and_args(
        "fast", ["--visual", "-k", "axe", "tests/ace/tui/visual"]
    )

    assert mode == "visual"
    assert args == ["-k", "axe", "tests/ace/tui/visual"]
