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
    assert result[-3:] == [
        "-m",
        runner.VISUAL_MARKER_EXPRESSION,
        "tests/ace/tui/visual",
    ]


def test_fast_mode_selects_non_slow_marker_to_include_visual_tests() -> None:
    runner = _load_run_pytest()

    result = runner._pytest_command("fast", [])

    assert result[-2:] == ["-m", runner.FAST_MARKER_EXPRESSION]
    assert result[-1] == "not slow"


def test_slow_mode_selects_slow_marker() -> None:
    runner = _load_run_pytest()

    result = runner._pytest_command("slow", ["tests/perf"])

    assert result[-3:] == ["-m", runner.SLOW_MARKER_EXPRESSION, "tests/perf"]


def test_cov_mode_selects_non_slow_marker_to_include_visual_tests() -> None:
    runner = _load_run_pytest()

    result = runner._pytest_command("cov", [])

    assert [
        "-m",
        runner.FAST_MARKER_EXPRESSION,
    ] in [result[index : index + 2] for index in range(len(result) - 1)]
    assert "--cov=src/sase" in result


def test_visual_flag_selects_visual_mode() -> None:
    runner = _load_run_pytest()

    mode, args = runner._resolve_mode_and_args(
        "fast", ["--visual", "-k", "axe", "tests/ace/tui/visual"]
    )

    assert mode == "visual"
    assert args == ["-k", "axe", "tests/ace/tui/visual"]


def test_fast_mode_sets_default_visual_png_tolerance(monkeypatch) -> None:
    runner = _load_run_pytest()
    monkeypatch.delenv(runner.VISUAL_PNG_MAX_DIFF_RATIO_ENV, raising=False)

    runner._configure_mode_environment("fast")

    assert (
        runner.os.environ[runner.VISUAL_PNG_MAX_DIFF_RATIO_ENV]
        == runner.BROAD_TEST_VISUAL_PNG_MAX_DIFF_RATIO
    )


def test_visual_mode_preserves_strict_visual_png_tolerance(monkeypatch) -> None:
    runner = _load_run_pytest()
    monkeypatch.delenv(runner.VISUAL_PNG_MAX_DIFF_RATIO_ENV, raising=False)

    runner._configure_mode_environment("visual")

    assert runner.VISUAL_PNG_MAX_DIFF_RATIO_ENV not in runner.os.environ


def test_sanitizes_commit_workflow_environment(monkeypatch) -> None:
    runner = _load_run_pytest()
    monkeypatch.setenv("SASE_COMMIT_METHOD", "create_pull_request")
    monkeypatch.setenv("SASE_COMMIT_METHOD_ALLOW_OVERRIDE", "1")
    monkeypatch.setenv("SASE_PR_NAME", "fix_just_tests")
    monkeypatch.setenv("SASE_PR_STATUS", "draft")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent")

    runner._sanitize_pytest_environment()

    for key in runner.PYTEST_ENV_UNSET_KEYS:
        assert key not in runner.os.environ
    assert runner.os.environ["SASE_AGENT_NAME"] == "agent"
