"""Tests for the Logs tab source registry (sase.ace.tui.logs.sources)."""

from __future__ import annotations

import json

from sase.ace.tui.logs.sources import log_sources
from sase.logs import (
    launch_failures_log_path,
    runs_log_path,
    tui_agent_loads_jsonl_path,
    tui_external_tools_jsonl_path,
    tui_git_ops_jsonl_path,
    tui_launch_timing_jsonl_path,
    tui_log_path,
    tui_stalls_jsonl_path,
    tui_toasts_jsonl_path,
)


def _source(source_id: str):
    for source in log_sources():
        if source.id == source_id:
            return source
    raise AssertionError(f"no log source {source_id!r}")


class TestRegistryShape:
    def test_launch_failures_is_first_default(self) -> None:
        sources = log_sources()
        assert sources[0].id == "launch_failures"
        assert [s.id for s in sources] == [
            "launch_failures",
            "tui",
            "tui_toasts",
            "tui_stalls",
            "tui_agent_loads",
            "tui_external_tools",
            "tui_git_ops",
            "tui_launch_timing",
            "runs",
            "events",
        ]

    def test_render_modes(self) -> None:
        assert _source("launch_failures").render == "text"
        assert _source("tui").render == "text"
        assert _source("tui_toasts").render == "toasts"
        assert _source("tui_stalls").render == "jsonl"
        assert _source("tui_agent_loads").render == "jsonl"
        assert _source("tui_external_tools").render == "jsonl"
        assert _source("tui_git_ops").render == "jsonl"
        assert _source("tui_launch_timing").render == "jsonl"
        assert _source("runs").render == "jsonl"
        assert _source("events").render == "jsonl"

    def test_paths_track_overrides(self) -> None:
        # log_sources() resolves canonical paths live, so isolated ~/.sase wins.
        assert _source("launch_failures").path == launch_failures_log_path()
        assert _source("tui").path == tui_log_path()
        assert _source("tui_toasts").path == tui_toasts_jsonl_path()
        assert _source("tui_stalls").path == tui_stalls_jsonl_path()
        assert _source("tui_agent_loads").path == tui_agent_loads_jsonl_path()
        assert _source("tui_external_tools").path == tui_external_tools_jsonl_path()
        assert _source("tui_git_ops").path == tui_git_ops_jsonl_path()
        assert _source("tui_launch_timing").path == tui_launch_timing_jsonl_path()


class TestReaders:
    def test_missing_file_is_empty(self) -> None:
        source = _source("launch_failures")
        assert not source.exists()
        assert source.line_count() == 0
        assert source.read_tail(50) == ""
        assert source.read_rendered_tail(50) == ""

    def test_text_tail_returns_last_lines(self) -> None:
        path = tui_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"line {i}\n" for i in range(100)))

        source = _source("tui")
        assert source.exists()
        assert source.line_count() == 100
        tail = source.read_tail(5)
        assert tail.splitlines() == [
            "line 95",
            "line 96",
            "line 97",
            "line 98",
            "line 99",
        ]
        # text sources render verbatim
        assert source.read_rendered_tail(5) == tail

    def test_jsonl_pretty_render(self) -> None:
        path = runs_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {
                "timestamp": "260617_120000",
                "event": "agent_run",
                "workflow": "crs",
                "status": "success",
            },
            {
                "timestamp": "260617_120500",
                "event": "agent_run",
                "workflow": "review",
                "status": "error",
            },
        ]
        path.write_text("".join(json.dumps(r) + "\n" for r in records))

        rendered = _source("runs").read_rendered_tail(10)
        lines = rendered.splitlines()
        assert len(lines) == 2
        # head fields (timestamp, event) come first, then key=value pairs
        assert lines[0].startswith("260617_120000  agent_run")
        assert "workflow=crs" in lines[0]
        assert "status=success" in lines[0]
        # raw JSON braces are not shown — it's pretty-rendered
        assert "{" not in rendered

    def test_jsonl_render_omits_traceback_and_truncates(self) -> None:
        path = runs_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": "260617_120000",
            "kind": "single",
            "traceback": "x" * 500,
            "prompt_preview": "y" * 500,
        }
        path.write_text(json.dumps(record) + "\n")

        rendered = _source("runs").read_rendered_tail(10)
        assert "traceback" not in rendered
        # long values are truncated with an ellipsis
        assert "..." in rendered
        assert "y" * 500 not in rendered

    def test_jsonl_render_tolerates_malformed_lines(self) -> None:
        path = runs_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('not json\n{"timestamp": "t", "event": "e"}\n')

        rendered = _source("runs").read_rendered_tail(10)
        lines = rendered.splitlines()
        assert lines[0] == "not json"
        assert lines[1].startswith("t  e")
