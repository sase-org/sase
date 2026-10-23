"""Proc-backed settlement must compose the real retained-output tail.

The original freeze path assigned null segment ranges when ``retention`` was
``None``, so follow-up prompts showed a gap notice instead of the command's
final lines. A second defect excerpted the head of the log under a "Last N
lines" heading. This regression drives the real
``settle_monitor_artifacts`` → frozen result → ``launch_followup_agent`` →
``compose_followup_prompt`` path and captures the prompt at process spawn.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

import sase.monitor.followup as followup_module
import sase.procs.spawn as spawn_module
from sase.agent.launch_types import AgentLaunchResult
from sase.monitor.logs import monitor_log_path
from sase.monitor.output import OutputCapture
from sase.monitor.proc_adapter import settle_monitor_artifacts
from sase.monitor.result_projection import TOTAL_RAW_EXCERPT_MAX_BYTES

from ._fixtures import isolate_from_enclosing_run
from ._followup_fixtures import (
    _SETTLE_TIMEOUT,
    _fake_result,
    _promote_and_start_monitor,
    _sandbox_home as _sandbox_home,
)

_EARLY_SENTINEL = "EARLY_SENTINEL_START_OF_LOG"
_FAIL_SUMMARY = "FAIL_SUMMARY_END_OF_LOG"
_CAPTURE_FALLBACK_SENTINEL = "CAPTURE_FALLBACK_SENTINEL"
_FAIL_LINES = (
    "# tests 3472",
    "# fail 5",
    "# cancelled 14",
    _FAIL_SUMMARY,
)


def _oversized_failed_log() -> str:
    ordinary = [f"ordinary passing test {index:05d}" for index in range(800)]
    body = "\n".join((_EARLY_SENTINEL, *ordinary, *_FAIL_LINES)) + "\n"
    encoded = body.encode()
    assert len(encoded) > TOTAL_RAW_EXCERPT_MAX_BYTES
    return body


def test_proc_settlement_followup_prompt_embeds_failed_log_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolate_from_enclosing_run(monkeypatch)
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(spawn_module.subprocess, "Popen", subprocess.Popen)
    meta_path = Path(monitor_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["monitor_next_output"] = "tail"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    output_path = meta.get("monitor_output_path") or monitor_log_path(monitor_dir)
    log_path = Path(str(output_path))
    log_path.write_text(_oversized_failed_log(), encoding="utf-8")

    state: dict[str, object] = {
        "artifacts_dir": monitor_dir,
        "proc_id": str(meta["monitor_id"]),
        "status": "error",
        "termination_reason": "nonzero",
        "exit_code": 1,
        "log_path": str(log_path),
    }
    settle_monitor_artifacts(state)

    on_disk = json.loads(meta_path.read_text(encoding="utf-8"))
    result_path = Path(str(on_disk["continuation_monitor_result_path"]))
    assert result_path.is_file()
    frozen = json.loads(result_path.read_text(encoding="utf-8"))
    retained = frozen["retained_log"]
    assert retained["complete"] is True
    assert retained["retained_ranges"]
    assert frozen["outcome"] == "failed"
    assert frozen["exit_code"] == 1

    log_path.write_text(_CAPTURE_FALLBACK_SENTINEL + "\n", encoding="utf-8")
    capture = OutputCapture()
    capture.append_bytes((_CAPTURE_FALLBACK_SENTINEL + "\n").encode())

    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    launch_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    monitor_meta = state["monitor_meta"]
    assert isinstance(monitor_meta, dict)
    launch_meta.update(monitor_meta)

    result = followup_module.launch_followup_agent(
        monitor_dir,
        launch_meta,
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=1.5,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    prompt = captured["prompt"]
    assert result.launched is True
    assert "| **Outcome** | FAILED — exit 1 |" in prompt
    assert "## Last " in prompt
    assert "lines of output" in prompt
    assert _FAIL_SUMMARY in prompt
    assert "# fail 5" in prompt
    assert "# cancelled 14" in prompt
    assert _EARLY_SENTINEL not in prompt
    assert _CAPTURE_FALLBACK_SENTINEL not in prompt
    assert "retained output gap" not in prompt
    assert on_disk["continuation_monitor_result_id"] == frozen["result_id"]
