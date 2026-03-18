"""Tests for sase.logs.run_log."""

import json
from pathlib import Path
from unittest.mock import patch

from sase.logs.run_log import log_agent_run, log_event


class TestLogAgentRun:
    def test_appends_jsonl_line(self, tmp_path: Path) -> None:
        runs_file = str(tmp_path / "runs.jsonl")
        with patch("sase.logs.run_log.RUNS_FILE", runs_file):
            log_agent_run(
                workflow="crs",
                project="sase",
                branch_or_workspace="feature-branch",
                workspace_num=3,
                model="claude-sonnet-4-20250514",
                llm_provider="anthropic",
                duration_seconds=142.5,
                status="success",
                artifacts_dir="/tmp/artifacts",
                prompt_preview="Hello world",
            )

        lines = Path(runs_file).read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["event"] == "agent_run"
        assert data["workflow"] == "crs"
        assert data["project"] == "sase"
        assert data["duration_seconds"] == 142.5
        assert data["status"] == "success"
        assert data["model"] == "claude-sonnet-4-20250514"

    def test_truncates_prompt_preview(self, tmp_path: Path) -> None:
        runs_file = str(tmp_path / "runs.jsonl")
        with patch("sase.logs.run_log.RUNS_FILE", runs_file):
            log_agent_run(
                workflow="crs",
                project="sase",
                branch_or_workspace="branch",
                workspace_num=1,
                duration_seconds=10,
                status="success",
                prompt_preview="x" * 200,
            )

        data = json.loads(Path(runs_file).read_text().strip())
        assert len(data["prompt_preview"]) == 100

    def test_omits_none_fields(self, tmp_path: Path) -> None:
        runs_file = str(tmp_path / "runs.jsonl")
        with patch("sase.logs.run_log.RUNS_FILE", runs_file):
            log_agent_run(
                workflow="crs",
                project="sase",
                branch_or_workspace="branch",
                workspace_num=1,
                duration_seconds=10,
                status="success",
            )

        data = json.loads(Path(runs_file).read_text().strip())
        assert "model" not in data
        assert "llm_provider" not in data

    def test_multiple_appends(self, tmp_path: Path) -> None:
        runs_file = str(tmp_path / "runs.jsonl")
        with patch("sase.logs.run_log.RUNS_FILE", runs_file):
            for i in range(3):
                log_agent_run(
                    workflow=f"wf{i}",
                    project="p",
                    branch_or_workspace="b",
                    workspace_num=i,
                    duration_seconds=float(i),
                    status="success",
                )

        lines = Path(runs_file).read_text().strip().splitlines()
        assert len(lines) == 3


class TestLogEvent:
    def test_appends_event(self, tmp_path: Path) -> None:
        events_file = str(tmp_path / "events.jsonl")
        with patch("sase.logs.run_log.EVENTS_FILE", events_file):
            log_event(event="hook_completed", hook="sase_lint", status="PASSED")

        data = json.loads(Path(events_file).read_text().strip())
        assert data["event"] == "hook_completed"
        assert data["hook"] == "sase_lint"
        assert data["status"] == "PASSED"
        assert "timestamp" in data

    def test_commit_event(self, tmp_path: Path) -> None:
        events_file = str(tmp_path / "events.jsonl")
        with patch("sase.logs.run_log.EVENTS_FILE", events_file):
            log_event(event="commit_created", cl_name="sase_feature_1")

        data = json.loads(Path(events_file).read_text().strip())
        assert data["event"] == "commit_created"
        assert data["cl_name"] == "sase_feature_1"
