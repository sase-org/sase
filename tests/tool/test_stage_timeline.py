from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time

import pytest

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_begin, tool_run_list, tool_run_show
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.query import ToolShowCliRequest, handle_show
from sase.tool.stage_protocol import (
    StageIngestor,
    ingest_event_file,
    unattributed_from_stages,
)


ROOT = Path(__file__).resolve().parents[2]
RUN_SILENT = ROOT / "tools" / "run_silent"
SASE = ROOT / ".venv" / "bin" / "sase"


def _home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
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
    return home


def _run(*argv: str, quiet: bool = False, verbose: bool = False) -> int:
    return execute_tool_run(
        ToolRunCliRequest(
            quiet=quiet,
            verbose=verbose,
            tail_lines=200,
            words=argv,
        )
    )


def _definition() -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "ad-hoc",
        "argv": ["true"],
        "description": "",
        "stages": "run_silent",
        "inputs": [],
        "env": [],
        "args": "allow",
        "fingerprint": {"repos": [], "toolchain": {}},
    }


def test_helper_never_opens_sqlite() -> None:
    source = (ROOT / "tools" / "_run_silent_record.py").read_text(encoding="utf-8")
    assert "import sqlite3" not in source
    assert "sase.core" not in source


def test_unwrapped_run_silent_is_unchanged(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.pop("SASE_TOOL_RUN_EVENTS", None)
    env.pop("SASE_TOOL_RUN_ID", None)
    env.pop("SASE_MONITOR_DIAGNOSTICS_DIR", None)
    env.pop("SASE_ARTIFACTS_DIR", None)
    ok = subprocess.run(
        [str(RUN_SILENT), "alpha", "true"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    fail = subprocess.run(
        [str(RUN_SILENT), "alpha", "sh", "-c", "printf boom; exit 7"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert ok.returncode == 0
    assert ok.stdout == "✓ alpha\n"
    assert fail.returncode == 7
    assert "✗ alpha" in fail.stdout
    assert "boom" in fail.stdout
    assert list(tmp_path.glob("**/*.jsonl")) == []


def test_repeated_names_failure_and_show_parity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path)
    pipeline = (
        f"{shlex.quote(str(RUN_SILENT))} alpha true && "
        f"{shlex.quote(str(RUN_SILENT))} alpha true && "
        f"{shlex.quote(str(RUN_SILENT))} beta sh -c 'exit 3' && "
        f"{shlex.quote(str(RUN_SILENT))} gamma true"
    )
    code = _run("--", "bash", "-lc", pipeline)
    captured = capsys.readouterr()
    assert code == 3
    assert "✓ alpha" in captured.out
    assert "✗ beta" in captured.out
    assert "gamma" not in captured.out
    run = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]
    shown = tool_run_show(run["run_id"])
    stages = shown["stages"]
    assert len(stages) == 3
    assert [stage["description"] for stage in stages] == ["alpha", "alpha", "beta"]
    assert stages[0]["stage_id"] != stages[1]["stage_id"]
    assert stages[0]["incomplete"] is False
    assert stages[1]["incomplete"] is False
    assert stages[2]["exit_code"] == 3
    for stage in stages:
        assert type(stage["elapsed_ms"]) is int
        assert stage["elapsed_ms"] >= 0
        assert type(stage["started_ts"]) is int
        assert type(stage["finished_ts"]) is int
        assert stage["finished_ts"] >= stage["started_ts"]
    json_code = handle_show(
        ToolShowCliRequest(run_id=run["run_id"], json=True, logs=False)
    )
    json_out = capsys.readouterr().out
    human_code = handle_show(
        ToolShowCliRequest(run_id=run["run_id"], json=False, logs=False)
    )
    human_out = capsys.readouterr().out
    assert json_code == 0
    assert human_code == 0
    payload = json.loads(json_out)
    assert payload["unattributed_ms"] == payload.get("unattributed_ms")
    assert type(payload["unattributed_ms"]) is int
    assert payload["unattributed_ms"] >= 0
    assert [stage["stage_id"] for stage in payload["stages"]] == [
        stage["stage_id"] for stage in stages
    ]
    for stage in stages:
        line = f"{stage['description']}  "
        assert line in human_out
        assert "UNATTRIB" in human_out


def test_compact_footer_matches_show_timeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENT_NAME", "fixture.agent")
    pipeline = (
        f"{shlex.quote(str(RUN_SILENT))} alpha true && "
        f"{shlex.quote(str(RUN_SILENT))} beta true"
    )
    code = _run("--", "bash", "-lc", pipeline)
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    assert "✓ alpha" not in captured.err
    run = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]
    shown = tool_run_show(run["run_id"])
    handle_show(ToolShowCliRequest(run_id=run["run_id"], json=True, logs=False))
    payload = json.loads(capsys.readouterr().out)
    for stage in shown["stages"]:
        assert f"{stage['description']}  " in captured.err
    assert "unattrib  " in captured.err
    assert payload["unattributed_ms"] is not None
    assert (
        str(payload["unattributed_ms"]) in captured.err or "unattrib  " in captured.err
    )


def test_unattributed_uses_interval_union_not_sum() -> None:
    stages = [
        {
            "started_ts": 1_000,
            "finished_ts": 1_300,
            "elapsed_ms": 300,
            "incomplete": False,
        },
        {
            "started_ts": 1_100,
            "finished_ts": 1_400,
            "elapsed_ms": 300,
            "incomplete": False,
        },
    ]
    attribution = unattributed_from_stages(stages, 500)
    assert attribution.unattributed_ms == 100
    assert attribution.incomplete is False
    missing = unattributed_from_stages(stages, None)
    assert missing.unattributed_ms is None
    assert missing.incomplete is True


def test_overlapping_producers_record_independent_stage_ids(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _home(monkeypatch, tmp_path)
    script = tmp_path / "overlap.py"
    script.write_text(
        "import subprocess, sys\n"
        f"rs = {str(RUN_SILENT)!r}\n"
        "left = subprocess.Popen([rs, 'left', 'sleep', '0.2'])\n"
        "right = subprocess.Popen([rs, 'right', 'sleep', '0.2'])\n"
        "raise SystemExit(left.wait() or right.wait())\n",
        encoding="utf-8",
    )
    code = _run("--", sys.executable, str(script))
    assert code == 0
    run = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]
    shown = tool_run_show(run["run_id"])
    stages = shown["stages"]
    assert {stage["description"] for stage in stages} == {"left", "right"}
    assert stages[0]["stage_id"] != stages[1]["stage_id"]
    duration = int(shown["run"]["duration_ms"])
    attribution = unattributed_from_stages(stages, duration)
    assert attribution.unattributed_ms is not None
    assert attribution.unattributed_ms >= 0
    assert attribution.unattributed_ms <= duration


def test_nested_runs_do_not_cross_attribute(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _home(monkeypatch, tmp_path)
    inner = tmp_path / "inner.py"
    inner.write_text(
        "from sase.tool.executor import ToolRunCliRequest, execute_tool_run\n"
        f"raise SystemExit(execute_tool_run(ToolRunCliRequest("
        f"quiet=False, verbose=False, tail_lines=200, "
        f"words=('--', {str(RUN_SILENT)!r}, 'inner', 'true'))))\n",
        encoding="utf-8",
    )
    pipeline = (
        f"{shlex.quote(str(RUN_SILENT))} outer true && "
        f"{shlex.quote(sys.executable)} {shlex.quote(str(inner))}"
    )
    code = _run("--", "bash", "-lc", pipeline)
    assert code == 0
    listed = tool_run_list({"schema_version": 1, "limit": 10})["runs"]
    assert len(listed) == 2
    parent = next(run for run in listed if run.get("parent_run_id") is None)
    child = next(run for run in listed if run.get("parent_run_id"))
    parent_show = tool_run_show(parent["run_id"])
    child_show = tool_run_show(child["run_id"])
    assert [stage["description"] for stage in parent_show["stages"]] == ["outer"]
    assert [stage["description"] for stage in child_show["stages"]] == ["inner"]
    assert all(stage["run_id"] == parent["run_id"] for stage in parent_show["stages"])
    assert all(stage["run_id"] == child["run_id"] for stage in child_show["stages"])


def test_malformed_and_torn_events_recover_valid_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = _home(monkeypatch, tmp_path)
    store = str(home / "tools" / "runs.sqlite")
    started = tool_run_begin(
        {
            "schema_version": 1,
            "definition": _definition(),
            "display_argv": ["true"],
            "project": "fixture",
            "commit_running": True,
            "now_ts": 10,
        },
        store_path=store,
    )
    run_id = started["run"]["run_id"]
    events = tmp_path / "events.jsonl"
    good_start = {
        "schema_version": 1,
        "kind": "started",
        "run_id": run_id,
        "stage_id": "st-good",
        "event_id": "ev-start",
        "description": "good",
        "started_ts": 1_000,
        "started_monotonic_ns": 1,
    }
    good_finish = {
        "schema_version": 1,
        "kind": "finished",
        "run_id": run_id,
        "stage_id": "st-good",
        "event_id": "ev-finish",
        "description": "good",
        "started_ts": 1_000,
        "finished_ts": 1_200,
        "elapsed_ms": 200,
        "exit_code": 0,
        "output_bytes": 0,
    }
    foreign = dict(good_finish)
    foreign["event_id"] = "ev-foreign"
    foreign["run_id"] = "other-run"
    foreign["stage_id"] = "st-foreign"
    events.write_text(
        json.dumps(good_start)
        + "\nnot-json\n"
        + json.dumps(good_finish)
        + "\n"
        + json.dumps(foreign)
        + '\n{"schema_version":1,"kind":"finished"',
        encoding="utf-8",
    )
    ingestor = StageIngestor(path=events, run_id=run_id, compact=False)
    ingestor.flush()
    assert any("malformed" in item for item in ingestor.diagnostics)
    assert any("torn" in item for item in ingestor.diagnostics)
    assert any("cross-run" in item for item in ingestor.diagnostics)
    shown = tool_run_show(run_id, store_path=store)
    assert len(shown["stages"]) == 1
    assert shown["stages"][0]["stage_id"] == "st-good"
    assert shown["stages"][0]["incomplete"] is False
    ingest_event_file(events, run_id)
    shown_again = tool_run_show(run_id, store_path=store)
    assert shown_again["stages"][0]["stage_id"] == "st-good"
    assert shown_again["stages"][0]["incomplete"] is False


def test_missing_finish_stays_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = _home(monkeypatch, tmp_path)
    store = str(home / "tools" / "runs.sqlite")
    started = tool_run_begin(
        {
            "schema_version": 1,
            "definition": _definition(),
            "display_argv": ["true"],
            "project": "fixture",
            "commit_running": True,
            "now_ts": 10,
        },
        store_path=store,
    )
    run_id = started["run"]["run_id"]
    events = tmp_path / "events.jsonl"
    events.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "started",
                "run_id": run_id,
                "stage_id": "st-open",
                "event_id": "ev-open",
                "description": "open",
                "started_ts": 5_000,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    ingest_event_file(events, run_id)
    shown = tool_run_show(run_id, store_path=store)
    assert shown["stages"][0]["incomplete"] is True
    assert shown["stages"][0].get("finished_ts") is None


@pytest.mark.skipif(not SASE.exists(), reason="workspace sase executable missing")
def test_interrupted_stage_and_lost_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _home(monkeypatch, tmp_path)
    env = os.environ.copy()
    env["SASE_HOME"] = str(home)
    for key in (
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_PROC_ID",
        "SASE_TOOL_RUN_ID",
    ):
        env.pop(key, None)
    marker = tmp_path / "started"
    child_pid_file = tmp_path / "child.pid"
    script = tmp_path / "hold.py"
    script.write_text(
        "import os, subprocess, time\n"
        f"open({str(child_pid_file)!r}, 'w').write(str(os.getpid()))\n"
        f"subprocess.run([{str(RUN_SILENT)!r}, 'hold', 'true'], check=False)\n"
        f"open({str(marker)!r}, 'w').write('ok')\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    proc = subprocess.Popen(
        [str(SASE), "tool", "run", "--", sys.executable, str(script)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    child_pid: int | None = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(0.05)  # sase-test-wait: run_silent finished before kill
        assert marker.exists()
        child_pid = int(child_pid_file.read_text(encoding="utf-8"))
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
        listed = subprocess.run(
            [str(SASE), "tool", "runs", "-j"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert listed.returncode == 0
        payload = json.loads(listed.stdout)
        run = payload["runs"][0]
        shown = tool_run_show(run["run_id"])
        assert shown["run"]["state"] == "lost"
        assert shown["stages"]
        assert shown["stages"][0]["description"] == "hold"
        assert shown["run"].get("duration_ms") is None
        assert shown["run"].get("exit_code") is None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except OSError:
                pass
