"""Baseline fixtures for monitor continuation costs and diagnostics."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from sase.continuation_baseline import measure_fork_render, _measure_prompt_components
from sase.history.chat import build_fork_injected_history
from sase.monitor.followup_prompt import compose_followup_prompt


_COMMON = {
    "command": "just check-full",
    "cwd": "/workspace/project",
    "reason": "Verify before continuing.",
    "started_at": "2026-09-11T10:00:00+00:00",
    "stopped_at": "2026-09-11T10:01:00+00:00",
    "elapsed_seconds": 60.0,
    "timeout_seconds": 2700.0,
    "monitor_id": "m4kqm4kqm4kq",
    "output_text": "SECRET_MONITOR_TAIL\n",
    "tail_lines": 200,
    "total_bytes": 20,
    "output_truncated": False,
    "next_action": "Fix any failures.",
}


def _monitor_proc_source(
    log_tail: str, *, next_output: str = "none"
) -> dict[str, object]:
    return {
        "kind": "proc",
        "name": "project--mon",
        "proc": {
            "proc_id": "m4kqm4kqm4kq",
            "is_monitor": True,
            "terminal": True,
            "failed": False,
            "shell_name": "project--mon",
            "command": "just check-full",
            "cwd": "/workspace/project",
            "project": "project",
            "started_at": "2026-09-11T10:00:00+00:00",
            "finished_at": "2026-09-11T10:01:00+00:00",
            "status": "completed",
            "exit_code": 0,
            "timeout_seconds": 2700.0,
            "elapsed_seconds": 60.0,
            "log_path": "/tmp/monitor.log",
            "log_tail": log_tail,
            "log_truncated": False,
            "monitor_lane": "project",
            "monitor_reason": "Verify before continuing.",
            "monitor_next_output": next_output,
            "monitor_followup_outcome": "launched",
            "monitor_followup_error": None,
        },
    }


def test_output_policy_none_suppresses_proc_tail_in_fork_render() -> None:
    followup = compose_followup_prompt(
        starter_name="project--0",
        monitor_state="completed",
        exit_code=0,
        next_output="none",
        **_COMMON,
    )
    assert "SECRET_MONITOR_TAIL" not in followup

    sources = [_monitor_proc_source("SECRET_MONITOR_TAIL\n")]
    rendered = build_fork_injected_history(sources)
    measurement = measure_fork_render(sources, rendered)

    assert "SECRET_MONITOR_TAIL" not in rendered
    assert measurement.prompt_sizes.evidence_bytes > 0
    assert measurement.node_counts.source_kind_counts == {"proc": 1}


def test_interrupted_starter_fixture_has_no_parent_history_prefix() -> None:
    prompt = compose_followup_prompt(
        starter_name=None,
        monitor_state="completed",
        exit_code=0,
        **_COMMON,
    )
    sizes = _measure_prompt_components(prompt)

    assert "#fork:" not in prompt
    assert sizes.history_bytes == 0
    assert sizes.local_bytes == sizes.total_expanded_bytes


def test_run_silent_records_failed_stage_and_preserves_early_exit(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    run_silent = Path.cwd() / "tools" / "run_silent"
    env = {**os.environ, "SASE_ARTIFACTS_DIR": str(artifacts)}
    fail_code = "print('boom'); raise SystemExit(7)"
    skipped_code = "print('must not run')"
    first = (
        f"{shlex.quote(str(run_silent))} 'stage one' "
        f"{shlex.quote(sys.executable)} -c "
        f"{shlex.quote(fail_code)}"
    )
    second = (
        f"{shlex.quote(str(run_silent))} 'stage two' "
        f"{shlex.quote(sys.executable)} -c "
        f"{shlex.quote(skipped_code)}"
    )

    result = subprocess.run(
        ["bash", "-lc", f"{first} && {second}"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 7
    assert "\u2717 stage one" in result.stdout
    assert "must not run" not in result.stdout
    records = [
        json.loads(line)
        for line in (artifacts / "continuation_stage_diagnostics.jsonl")
        .read_text()
        .splitlines()
    ]
    assert len(records) == 1
    assert records[0]["description"] == "stage one"
    assert records[0]["status"] == "failed"
    assert records[0]["exit_code"] == 7
    assert records[0]["output_bytes"] >= len("boom\n")
