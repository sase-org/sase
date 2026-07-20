"""Launch matching, retry-chain, and registry-GC chop lifecycle coverage."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.chop_agents import (
    _record_chop_agent_launch,
    get_chop_agent_records,
)
from sase.axe.chop_lifecycle import finalize_launched_chop_runs
from sase.axe.state import (
    ChopRunEntry,
    chop_run_log_path,
    finish_chop_run,
    read_chop_run,
    start_chop_run,
)
from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def _launched_entry(
    run_id: str,
    *,
    pid: int,
    launches: list[dict[str, object]] | None = None,
) -> None:
    entry = ChopRunEntry(
        run_id=run_id,
        lumberjack_name="docs",
        chop_name="docs",
        started_at="2026-07-18T12:00:00+00:00",
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(entry)
    finish_chop_run(
        "docs",
        "docs",
        run_id,
        status="launched",
        finished_at=None,
        duration_ms=1,
        exit_code=0,
        agent_pid=pid,
        launches=launches or [{"pid": pid}],
    )


def _record_agent(
    run_id: str,
    *,
    pid: int,
    timestamp: str,
) -> None:
    _record_chop_agent_launch(
        lumberjack_name="docs",
        chop_name="docs",
        run_id=run_id,
        pid=pid,
        project_file="/projects/sase/sase.sase",
        project_name="sase",
        workspace_num=1,
        workflow_name="ace(run)-260718_120000",
        cl_name="sase",
        timestamp=timestamp,
        prompt="refresh",
    )


def test_lifecycle_ignores_unmatched_registry_records(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120005_000000"
    _launched_entry(
        run_id,
        pid=321,
        launches=[{"pid": 321, "artifacts_timestamp": "20260718120005"}],
    )
    _record_agent(run_id, pid=321, timestamp="260718_120005")
    _record_agent(run_id, pid=4321, timestamp="260101_120000")
    artifacts = resolve_agent_artifact_timestamp_path(
        "sase", "ace-run", "20260718120005"
    )
    artifacts.mkdir(parents=True)
    (artifacts / "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )

    assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"
    output = chop_run_log_path("docs", "docs", run_id).read_text(encoding="utf-8")
    assert "Ignored 1 unmatched agent registry record" in output
    assert "pid 4321" in output


def test_lifecycle_follows_retry_chain_until_successor_finishes(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120006_000000"
    timestamps = ["20260718120006", "20260718120007", "20260718120008"]
    _launched_entry(
        run_id,
        pid=321,
        launches=[{"pid": 321, "artifacts_timestamp": timestamps[0]}],
    )
    _record_agent(run_id, pid=321, timestamp="260718_120006")
    _record_agent(run_id, pid=654, timestamp="260718_120007")
    _record_agent(run_id, pid=987, timestamp="260718_120008")

    for timestamp, successor in zip(timestamps, timestamps[1:], strict=False):
        artifacts = resolve_agent_artifact_timestamp_path("sase", "ace-run", timestamp)
        artifacts.mkdir(parents=True)
        (artifacts / "done.json").write_text(
            json.dumps(
                {
                    "outcome": "failed",
                    "retried_as_timestamp": successor,
                }
            ),
            encoding="utf-8",
        )

    with patch("sase.axe.chop_lifecycle.is_process_running", return_value=True):
        assert finalize_launched_chop_runs("docs", ["docs"]) == 0
    active = read_chop_run("docs", "docs", run_id)
    assert active is not None
    assert active.status == "launched"

    successor_artifacts = resolve_agent_artifact_timestamp_path(
        "sase", "ace-run", timestamps[-1]
    )
    successor_artifacts.mkdir(parents=True, exist_ok=True)
    (successor_artifacts / "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )

    assert finalize_launched_chop_runs("docs", ["docs"]) == 1
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"


def test_lifecycle_fails_closed_when_equal_count_record_does_not_match_launch(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120009_000000"
    _launched_entry(
        run_id,
        pid=321,
        launches=[{"pid": 321, "artifacts_timestamp": "20260718120009"}],
    )
    _record_agent(run_id, pid=321, timestamp="260101_120000")

    assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_failed"
    assert entry.error is not None
    assert "linkage incomplete" in entry.error
    output = chop_run_log_path("docs", "docs", run_id).read_text(encoding="utf-8")
    assert "Ignored 1 unmatched agent registry record" in output


def test_lifecycle_garbage_collects_orphaned_and_terminal_run_records(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    terminal_run_id = "20260718T120014_000000"
    terminal_entry = ChopRunEntry(
        run_id=terminal_run_id,
        lumberjack_name="docs",
        chop_name="tg_inbound",
        started_at="2026-07-18T12:00:14+00:00",
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(terminal_entry)
    finish_chop_run(
        "docs",
        "tg_inbound",
        terminal_run_id,
        status="success",
        finished_at="2026-07-18T12:00:15+00:00",
        duration_ms=1000,
    )
    _record_chop_agent_launch(
        lumberjack_name="docs",
        chop_name="tg_inbound",
        run_id=terminal_run_id,
        pid=111,
        project_file="/projects/sase/sase.sase",
        project_name="sase",
        workspace_num=1,
        workflow_name="ace(run)-260718_120014",
        cl_name="sase",
        timestamp="260718_120014",
        prompt="telegram",
    )
    _record_chop_agent_launch(
        lumberjack_name="docs",
        chop_name="legacy",
        run_id="missing-run",
        pid=222,
        project_file="/projects/sase/sase.sase",
        project_name="sase",
        workspace_num=1,
        workflow_name="ace(run)-260718_120015",
        cl_name="sase",
        timestamp="260718_120015",
        prompt="legacy",
    )

    active_run_id = "20260718T120016_000000"
    _launched_entry(active_run_id, pid=333)
    _record_agent(active_run_id, pid=333, timestamp="260718_120016")

    with patch("sase.axe.chop_lifecycle.is_process_running", return_value=True):
        assert finalize_launched_chop_runs("docs", ["docs"]) == 0

    records = get_chop_agent_records("docs")
    assert [(record.chop_name, record.run_id) for record in records] == [
        ("docs", active_run_id)
    ]
