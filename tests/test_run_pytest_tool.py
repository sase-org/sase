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


def test_fast_mode_selects_non_slow_marker_to_include_visual_tests(
    monkeypatch,
) -> None:
    runner = _load_run_pytest()
    monkeypatch.delenv(runner.EXCLUDE_VISUAL_ENV, raising=False)

    result = runner._pytest_command("fast", [])

    assert "-n" in result
    assert "--dist=loadfile" in result
    assert result[-2:] == ["-m", runner.FAST_MARKER_EXPRESSION]
    assert result[-1] == "not slow"


def _set_mem_available(
    monkeypatch, runner: ModuleType, tmp_path: Path, available_gib: int
) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        f"MemTotal: 99999999 kB\nMemAvailable: {available_gib * 1024 * 1024} kB\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "MEMINFO_PATH", meminfo)


def test_worker_count_caps_at_quarter_of_cpus(monkeypatch, tmp_path: Path) -> None:
    runner = _load_run_pytest()
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.setattr(runner.os, "cpu_count", lambda: 8)
    _set_mem_available(monkeypatch, runner, tmp_path, available_gib=64)

    assert runner._worker_count() == "2"


def test_worker_count_uses_at_least_one_worker(monkeypatch, tmp_path: Path) -> None:
    runner = _load_run_pytest()
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.setattr(runner.os, "cpu_count", lambda: 2)
    _set_mem_available(monkeypatch, runner, tmp_path, available_gib=64)

    assert runner._worker_count() == "1"


def test_worker_count_shrinks_under_memory_pressure(
    monkeypatch, tmp_path: Path
) -> None:
    runner = _load_run_pytest()
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.setattr(runner.os, "cpu_count", lambda: 64)
    _set_mem_available(monkeypatch, runner, tmp_path, available_gib=3)

    assert runner._worker_count() == "2"


def test_worker_count_preserves_cpu_limit_with_plentiful_memory(
    monkeypatch, tmp_path: Path
) -> None:
    runner = _load_run_pytest()
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.setattr(runner.os, "cpu_count", lambda: 64)
    _set_mem_available(monkeypatch, runner, tmp_path, available_gib=64)

    assert runner._worker_count() == "16"


def test_worker_count_falls_back_when_meminfo_is_unreadable(
    monkeypatch, tmp_path: Path
) -> None:
    runner = _load_run_pytest()
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.setattr(runner.os, "cpu_count", lambda: 64)
    monkeypatch.setattr(runner, "MEMINFO_PATH", tmp_path / "missing-meminfo")

    assert runner._worker_count() == "16"


def test_worker_count_prefers_env_override(monkeypatch) -> None:
    runner = _load_run_pytest()
    monkeypatch.setenv("SASE_PYTEST_WORKERS", "12")

    assert runner._worker_count() == "12"


def test_inline_snapshot_fix_disables_default_xdist() -> None:
    runner = _load_run_pytest()

    result = runner._pytest_command(
        "fast", ["--inline-snapshot=fix", "tests/test_run_pytest_tool.py"]
    )

    assert "-n" not in result
    assert "--dist=loadfile" not in result
    assert result[-2:] == ["--inline-snapshot=fix", "tests/test_run_pytest_tool.py"]


def test_inline_snapshot_separate_value_disables_default_xdist() -> None:
    runner = _load_run_pytest()

    result = runner._pytest_command(
        "fast", ["--inline-snapshot", "short-report", "tests/test_run_pytest_tool.py"]
    )

    assert "-n" not in result
    assert "--dist=loadfile" not in result


def test_inline_snapshot_disable_preserves_default_xdist() -> None:
    runner = _load_run_pytest()

    result = runner._pytest_command(
        "fast", ["--inline-snapshot=disable", "tests/test_run_pytest_tool.py"]
    )

    assert "-n" in result
    assert "--dist=loadfile" in result


def test_inline_snapshot_fix_shortcut_disables_default_xdist() -> None:
    runner = _load_run_pytest()

    result = runner._pytest_command("fast", ["--fix", "tests/test_run_pytest_tool.py"])

    assert "-n" not in result
    assert "--dist=loadfile" not in result


def test_slow_mode_selects_slow_marker() -> None:
    runner = _load_run_pytest()

    result = runner._pytest_command("slow", ["tests/perf"])

    assert result[-3:] == ["-m", runner.SLOW_MARKER_EXPRESSION, "tests/perf"]


def test_cov_mode_selects_non_slow_marker_to_include_visual_tests(monkeypatch) -> None:
    runner = _load_run_pytest()
    monkeypatch.setenv(runner.EXCLUDE_VISUAL_ENV, "false")

    result = runner._pytest_command("cov", [])

    assert [
        "-m",
        runner.FAST_MARKER_EXPRESSION,
    ] in [result[index : index + 2] for index in range(len(result) - 1)]
    assert "--cov=src/sase" in result


def test_cov_mode_can_exclude_visual_tests_for_noncanonical_ci_legs(
    monkeypatch,
) -> None:
    runner = _load_run_pytest()
    monkeypatch.setenv(runner.EXCLUDE_VISUAL_ENV, "true")

    result = runner._pytest_command("cov", [])

    assert [
        "-m",
        runner.FAST_NON_VISUAL_MARKER_EXPRESSION,
    ] in [result[index : index + 2] for index in range(len(result) - 1)]
    assert "--cov=src/sase" in result


def test_visual_flag_selects_visual_mode() -> None:
    runner = _load_run_pytest()

    mode, args = runner._resolve_mode_and_args(
        "fast", ["--visual", "-k", "axe", "tests/ace/tui/visual"]
    )

    assert mode == "visual"
    assert args == ["-k", "axe", "tests/ace/tui/visual"]


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
