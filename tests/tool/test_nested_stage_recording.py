"""A stage's children never record stages or diagnostics into the enclosing run."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_list, tool_run_show
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from tests._conftest_environment import TOOL_RUN_RECORDING_ENV_VARS
from tests._tmp_leak_guard import DISABLED_ENV as TMP_LEAK_GUARD_DISABLED_ENV


ROOT = Path(__file__).resolve().parents[2]
RUN_SILENT = ROOT / "tools" / "run_silent"
THIS_FILE = Path(__file__).resolve()
PROBE_ENV = "SASE_NESTED_STAGE_PROBE"

_PATH = os.environ.get("PATH", "/usr/bin:/bin")


def _home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_MONITOR_ID", raising=False)
    monkeypatch.delenv("SASE_MONITOR_ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("SASE_PROC_ID", raising=False)
    monkeypatch.delenv("SASE_TOOL_RUN_ID", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()


def _run(*argv: str) -> int:
    return execute_tool_run(
        ToolRunCliRequest(quiet=False, verbose=False, tail_lines=200, words=argv)
    )


def _newest_stages() -> list[dict[str, object]]:
    listed = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]
    return list(tool_run_show(listed["run_id"])["stages"])


def _nested_failure() -> str:
    return f"{shlex.quote(str(RUN_SILENT))} inner sh -c 'printf inner-boom; exit 3'"


def test_nested_run_silent_records_only_the_top_level_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)

    code = _run("--", str(RUN_SILENT), "outer", "bash", "-c", _nested_failure())

    assert code == 3
    stages = _newest_stages()
    assert [stage["description"] for stage in stages] == ["outer"]
    assert stages[0]["exit_code"] == 3
    assert stages[0]["incomplete"] is False


def test_sibling_top_level_stages_are_still_recorded_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    quoted = shlex.quote(str(RUN_SILENT))

    code = _run(
        "--",
        "bash",
        "-c",
        f"{quoted} first true && {quoted} second bash -c {shlex.quote(_nested_failure())}",
    )

    assert code == 3
    assert [stage["description"] for stage in _newest_stages()] == ["first", "second"]


def test_nested_run_silent_leaves_the_outer_monitor_diagnostics_alone(
    tmp_path: Path,
) -> None:
    diagnostics = tmp_path / "diagnostics"
    env = {"PATH": _PATH, "SASE_MONITOR_DIAGNOSTICS_DIR": str(diagnostics)}

    completed = subprocess.run(
        [str(RUN_SILENT), "outer", "bash", "-c", _nested_failure()],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 3
    reports = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (diagnostics / "stages").glob("*.json")
    ]
    assert [report["name"] for report in reports] == ["outer"]


def test_nested_run_silent_keeps_the_parent_run_link_variable(
    tmp_path: Path,
) -> None:
    env = {
        "PATH": _PATH,
        "SASE_TOOL_RUN_EVENTS": str(tmp_path / "events.jsonl"),
        "SASE_TOOL_RUN_ID": "outer-run",
    }
    probe = "import os; print(sorted(k for k in os.environ if k.startswith('SASE_')))"

    completed = subprocess.run(
        [str(RUN_SILENT), "outer", sys.executable, "-c", probe],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    # A passing stage discards its output, so run the probe once more visibly.
    visible = subprocess.run(
        [
            str(RUN_SILENT),
            "outer",
            sys.executable,
            "-c",
            probe + "; raise SystemExit(1)",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert visible.returncode == 1
    assert "SASE_TOOL_RUN_ID" in visible.stdout
    assert "SASE_TOOL_RUN_EVENTS" not in visible.stdout
    assert "SASE_MONITOR_DIAGNOSTICS_DIR" not in visible.stdout


@pytest.mark.parametrize(
    ("stage", "expected_code", "expected_stdout"),
    [
        (["true"], 0, "✓ alpha\n"),
        ([":"], 0, "✓ alpha\n"),
        (["sh", "-c", "printf boom; exit 7"], 7, "✗ alpha\nboom"),
        (["sh", "-c", "echo out; echo err >&2; exit 4"], 4, "✗ alpha\nout\nerr\n"),
        (["false"], 1, "✗ alpha\n"),
    ],
)
def test_run_silent_output_is_unchanged_without_recording_variables(
    stage: list[str], expected_code: int, expected_stdout: str, tmp_path: Path
) -> None:
    env = {"PATH": _PATH}

    completed = subprocess.run(
        [str(RUN_SILENT), "alpha", *stage],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == expected_code
    assert completed.stdout == expected_stdout.encode("utf-8")
    assert completed.stderr == b""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(
    os.environ.get(PROBE_ENV) != "1",
    reason="probe body; run by a stageless ToolRun in the test below",
)
def test_probe_child_pytest_runs_a_failing_stage() -> None:
    for name in TOOL_RUN_RECORDING_ENV_VARS:
        assert name not in os.environ, f"{name} leaked into the test session"
    completed = subprocess.run(
        [str(RUN_SILENT), "probe stage", "sh", "-c", "exit 3"],
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 3


def _nested_pytest_argv(*node_ids: str) -> list[str]:
    # The caller must also set TMP_LEAK_GUARD_DISABLED_ENV: a nested session
    # shares the outer suite's private TMPDIR, so its leak guard would report
    # entries that the outer suite's other workers are creating meanwhile.
    return [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:randomly",
        "-p",
        "no:cacheprovider",
        "-n0",
        "-c",
        str(ROOT / "pyproject.toml"),
        "--rootdir",
        str(ROOT),
        *node_ids,
    ]


def test_child_pytest_of_a_stageless_run_records_no_stage_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    diagnostics = tmp_path / "outer-diagnostics"
    monkeypatch.setenv(PROBE_ENV, "1")
    monkeypatch.setenv(TMP_LEAK_GUARD_DISABLED_ENV, "1")
    monkeypatch.setenv("SASE_MONITOR_DIAGNOSTICS_DIR", str(diagnostics))
    monkeypatch.chdir(ROOT)

    code = _run(
        "--",
        *_nested_pytest_argv(
            f"{THIS_FILE}::test_probe_child_pytest_runs_a_failing_stage"
        ),
    )

    assert code == 0
    assert _newest_stages() == []
    assert not diagnostics.exists()


def test_fixtures_that_run_run_silent_leave_the_enclosing_run_alone(
    tmp_path: Path,
) -> None:
    events = tmp_path / "events.jsonl"
    diagnostics = tmp_path / "outer-diagnostics"
    env = {
        **os.environ,
        "SASE_TOOL_RUN_EVENTS": str(events),
        "SASE_TOOL_RUN_ID": "outer-run",
        "SASE_MONITOR_DIAGNOSTICS_DIR": str(diagnostics),
        TMP_LEAK_GUARD_DISABLED_ENV: "1",
    }
    monitor_tests = ROOT / "tests" / "monitor"

    completed = subprocess.run(
        _nested_pytest_argv(
            f"{monitor_tests / 'test_continuation_baseline.py'}"
            "::test_run_silent_records_failed_stage_and_preserves_early_exit",
            f"{monitor_tests / 'test_monitor_diagnostics.py'}"
            "::test_run_silent_writes_isolated_monitor_stage_report",
        ),
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert not events.exists()
    assert not diagnostics.exists()
