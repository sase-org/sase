"""Opt-in continuation for recorded ``stages: run_silent`` tools."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_list, tool_run_show
from sase.tool.executor import ToolRunCliRequest, execute_tool_run


ROOT = Path(__file__).resolve().parents[2]
RUN_SILENT = ROOT / "tools" / "run_silent"


def _home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    for name in (
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_PROC_ID",
        "SASE_TOOL_CONTINUE",
        "SASE_TOOL_PYTHON",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_EVENTS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


def _project(tmp_path: Path, script: str, *, stages: str = "run_silent") -> Path:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    sase_dir = root / "sase"
    sase_dir.mkdir()
    catalog = {
        "tools": {
            "check": {
                "argv": ["bash", "-lc", script],
                "description": "continuation fixture",
                "stages": stages,
                "inputs": [],
                "env": [],
                "args": "deny",
                "fingerprint": {"repos": [], "toolchain": {}},
            }
        }
    }
    (sase_dir / "sase.yml").write_text(yaml.safe_dump(catalog), encoding="utf-8")
    return root


def _stage(description: str, shell: str) -> str:
    return f"{shlex.quote(str(RUN_SILENT))} {shlex.quote(description)} {shell}"


def _run(*, keep_going: bool = False, fail_fast: bool = False) -> int:
    return execute_tool_run(
        ToolRunCliRequest(
            quiet=False,
            verbose=False,
            tail_lines=200,
            words=("check",),
            keep_going=keep_going,
            fail_fast=fail_fast,
        )
    )


def _newest() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run_id = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]["run_id"]
    shown = tool_run_show(run_id)
    logs = shown["run"]["logs"]
    events = Path(str(logs["events_path"]))
    records = [json.loads(line) for line in events.read_text().splitlines()]
    return shown, records


def test_keep_going_runs_every_stage_and_exits_with_first_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _home(monkeypatch, tmp_path)
    script = " && ".join(
        (
            _stage("one", "sh -c 'exit 7'"),
            _stage("two", "true"),
            _stage("three", "sh -c 'exit 9'"),
            _stage("four", "true"),
            f"{shlex.quote(str(RUN_SILENT))} --finish",
        )
    )
    root = _project(tmp_path, script)
    monkeypatch.chdir(root)

    assert _run(keep_going=True) == 7
    captured = capsys.readouterr()
    assert "✗ 2 stage(s) failed; continued past them (first exit 7)" in captured.out
    shown, records = _newest()
    assert shown["run"]["state"] == "failed"
    assert [stage["description"] for stage in shown["stages"]] == [
        "one",
        "two",
        "three",
        "four",
    ]
    continued = [record for record in records if record["kind"] == "continued"]
    assert [record["exit_code"] for record in continued] == [7, 9]
    assert all(record["reason"] == "mode_always" for record in continued)
    assert records[-1]["kind"] == "recipe_finished"
    assert records[-1]["first_continued_exit_code"] == 7


def test_missing_finish_cannot_turn_a_continued_failure_green(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    root = _project(tmp_path, _stage("one", "sh -c 'exit 7'"))
    monkeypatch.chdir(root)

    assert _run(keep_going=True) == 1
    shown, records = _newest()
    assert shown["run"]["state"] == "failed"
    assert shown["run"]["exit_code"] == 1
    assert "continuation_unfinished" in shown["run"]["diagnostics"]
    assert any(record["kind"] == "continued" for record in records)
    assert not any(record["kind"] == "recipe_finished" for record in records)


def test_fail_fast_stops_at_the_first_failed_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    script = " && ".join(
        (
            _stage("one", "sh -c 'exit 7'"),
            _stage("two", "true"),
            f"{shlex.quote(str(RUN_SILENT))} --finish",
        )
    )
    root = _project(tmp_path, script)
    monkeypatch.chdir(root)

    assert _run(fail_fast=True) == 7
    shown, records = _newest()
    assert [stage["description"] for stage in shown["stages"]] == ["one"]
    assert [record["kind"] for record in records if record["kind"] == "stopped"] == [
        "stopped"
    ]


@pytest.mark.parametrize("outcomes", tuple(itertools.product((0, 3), repeat=3)))
@pytest.mark.parametrize("finish", (False, True))
def test_continuation_never_returns_zero_after_a_failed_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    outcomes: tuple[int, int, int],
    finish: bool,
) -> None:
    _home(monkeypatch, tmp_path)
    lines = [
        _stage(f"stage-{index}", "true" if code == 0 else f"sh -c 'exit {code}'")
        for index, code in enumerate(outcomes, start=1)
    ]
    if finish:
        lines.append(f"{shlex.quote(str(RUN_SILENT))} --finish")
    root = _project(tmp_path, "; ".join(lines))
    monkeypatch.chdir(root)

    code = _run(keep_going=True)
    if any(outcomes):
        assert code != 0
    else:
        assert code == 0


def test_stop_after_a_continued_failure_keeps_the_first_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    script = "; ".join(
        (
            _stage("first", "sh -c 'exit 7'"),
            "SASE_TOOL_CONTINUE=unknown " + _stage("second", "sh -c 'exit 9'"),
        )
    )
    root = _project(tmp_path, script)
    monkeypatch.chdir(root)

    assert _run(keep_going=True) == 7


def test_unknown_handshake_mode_is_fail_fast(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    env = {
        "PATH": "/usr/bin:/bin",
        "SASE_TOOL_CONTINUE": "unknown",
        "SASE_TOOL_PYTHON": sys.executable,
        "SASE_TOOL_RUN_EVENTS": str(events),
        "SASE_TOOL_RUN_ID": "run-1",
    }

    completed = subprocess.run(
        [str(RUN_SILENT), "stage", "sh", "-c", "exit 7"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 7
    records = [json.loads(line) for line in events.read_text().splitlines()]
    stopped = next(record for record in records if record["kind"] == "stopped")
    assert stopped["mode"] == "unknown"
    assert stopped["reason"] == "helper_error"


def test_finish_is_silent_without_the_handshake(tmp_path: Path) -> None:
    completed = subprocess.run(
        [str(RUN_SILENT), "--finish"],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
        cwd=tmp_path,
    )

    assert completed.returncode == 0
    assert completed.stdout == ""
    assert completed.stderr == ""


def test_continuation_controls_reject_named_stageless_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path)
    root = _project(tmp_path, "true", stages="none")
    monkeypatch.chdir(root)

    assert (
        execute_tool_run(
            ToolRunCliRequest(
                quiet=False,
                verbose=False,
                tail_lines=200,
                words=("check",),
                keep_going=True,
            )
        )
        == 2
    )
    assert "stages: run_silent" in capsys.readouterr().err


@pytest.mark.parametrize(
    "cli_request",
    (
        ToolRunCliRequest(
            quiet=False,
            verbose=False,
            tail_lines=200,
            words=("--", "true"),
            keep_going=True,
        ),
        ToolRunCliRequest(
            quiet=False,
            verbose=False,
            tail_lines=200,
            words=("--", "true"),
            fail_fast=True,
        ),
        ToolRunCliRequest(
            quiet=False,
            verbose=False,
            tail_lines=200,
            words=("check",),
            hand_off=True,
            keep_going=True,
        ),
    ),
)
def test_continuation_controls_reject_invalid_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    cli_request: ToolRunCliRequest,
) -> None:
    _home(monkeypatch, tmp_path)

    assert execute_tool_run(cli_request) == 2
    assert capsys.readouterr().err
