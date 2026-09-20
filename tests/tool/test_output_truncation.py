"""Retained-output truncation is an explicit, durable fact, not a silent cut."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_list
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.logs import (
    BoundedLogSink,
    RunLogBudget,
    read_truncation_messages,
    record_truncation,
    truncation_diagnostics,
)
from sase.tool.query import ToolShowCliRequest, handle_show
from sase.tool.stage_protocol import StageIngestor


ROOT = Path(__file__).resolve().parents[2]
RUN_SILENT = ROOT / "tools" / "run_silent"
FLOOD = "import sys\nfor i in range(1, 501):\n    print(f'line {i}')\nsys.exit(1)\n"


def _home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cap: int) -> Path:
    home = tmp_path / "home"
    (home / "cfg").mkdir(parents=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    for name in (
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_PROC_ID",
        "SASE_TOOL_RUN_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    (tmp_path / "sase").mkdir()
    (tmp_path / "sase" / "sase.yml").write_text(
        f"tool_runs:\n  run_log_max_bytes: {cap}\n", encoding="utf-8"
    )
    clear_config_cache()
    return home


def _run(*words: str, quiet: bool = False, verbose: bool = False) -> int:
    return execute_tool_run(
        ToolRunCliRequest(quiet=quiet, verbose=verbose, tail_lines=3, words=words)
    )


def test_sinks_report_dropped_bytes_per_stream(tmp_path: Path) -> None:
    budget = RunLogBudget(10)
    out = BoundedLogSink(tmp_path / "out.log", budget, tail_lines=3)
    err = BoundedLogSink(tmp_path / "err.log", budget, tail_lines=3)
    out.write(b"0123456789ab")
    err.write(b"xyz")
    out.close()
    err.close()
    assert (tmp_path / "out.log").read_bytes() == b"0123456789"
    assert truncation_diagnostics(out, err, budget) == [
        "retained output truncated: stdout dropped 2 bytes, stderr dropped 3 bytes "
        "(run_log_max_bytes=10)"
    ]


def test_no_diagnostic_when_nothing_was_dropped(tmp_path: Path) -> None:
    budget = RunLogBudget(100)
    sink = BoundedLogSink(tmp_path / "out.log", budget, tail_lines=3)
    sink.write(b"small\n")
    sink.close()
    assert truncation_diagnostics(sink, None, budget) == []
    assert record_truncation(tmp_path / "events.jsonl", "run-1", []) is False
    assert not (tmp_path / "events.jsonl").exists()


def test_write_failure_is_reported_as_a_failure_not_a_cap(tmp_path: Path) -> None:
    budget = RunLogBudget(1000)
    sink = BoundedLogSink(tmp_path / "out.log", budget, tail_lines=3)
    sink.failed = True
    sink.write(b"lost bytes")
    assert truncation_diagnostics(sink, None, budget) == [
        "retained output truncated: stdout dropped 10 bytes (after a log write failure)"
    ]


def test_record_round_trips_and_only_matches_its_own_run(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    message = "retained output truncated: stdout dropped 9 bytes (run_log_max_bytes=1)"
    assert record_truncation(events, "run-1", [message]) is True
    record_truncation(tmp_path / "events.jsonl", "other-run", ["not mine"])
    assert read_truncation_messages(str(events), "run-1") == [message]
    assert read_truncation_messages(str(events), "run-3") == []
    assert read_truncation_messages(None, "run-1") == []
    assert read_truncation_messages(str(tmp_path / "missing.jsonl"), "run-1") == []


def test_stage_ingestor_skips_the_output_record_without_a_diagnostic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path, 4096)
    events = tmp_path / "events.jsonl"
    record_truncation(events, "run-1", ["retained output truncated: stdout dropped 1"])
    ingestor = StageIngestor(path=events, run_id="run-1")
    ingestor.flush()
    assert ingestor.diagnostics == []
    assert ingestor.stages == {}


def test_overflow_is_explicit_in_footer_replay_and_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path, 100)
    assert _run("--", sys.executable, "-c", FLOOD, quiet=True) == 1
    footer = capsys.readouterr().err
    assert "retained output truncated: stdout dropped" in footer
    assert "(run_log_max_bytes=100)" in footer
    run_id = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]["run_id"]

    assert handle_show(ToolShowCliRequest(run_id=run_id, json=True, logs=False)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["output_truncation"]) == 1
    assert "run_log_max_bytes=100" in payload["output_truncation"][0]

    assert handle_show(ToolShowCliRequest(run_id=run_id, json=False, logs=True)) == 0
    replay = capsys.readouterr()
    assert 0 < len(replay.out) <= 100
    assert "retained output truncated" in replay.err


def test_passthrough_and_untruncated_runs_stay_quiet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path, 1_000_000)
    assert _run("--", sys.executable, "-c", FLOOD) == 1
    captured = capsys.readouterr()
    assert "line 500" in captured.out
    assert "truncated" not in captured.err
    run_id = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]["run_id"]
    assert handle_show(ToolShowCliRequest(run_id=run_id, json=True, logs=False)) == 0
    assert json.loads(capsys.readouterr().out)["output_truncation"] == []


def test_run_silent_locks_the_events_file_and_leaves_no_sibling_lock(
    tmp_path: Path,
) -> None:
    events = tmp_path / "events.jsonl"
    env = {
        "SASE_TOOL_RUN_EVENTS": str(events),
        "SASE_TOOL_RUN_ID": "run-x",
        "PATH": "/usr/bin:/bin",
    }
    for name in ("first", "second"):
        subprocess.run(
            [str(RUN_SILENT), name, "true"], env=env, check=True, capture_output=True
        )
    assert sorted(p.name for p in tmp_path.iterdir()) == ["events.jsonl"]
    kinds = [json.loads(line)["kind"] for line in events.read_text().splitlines()]
    assert kinds == ["started", "finished", "started", "finished"]
