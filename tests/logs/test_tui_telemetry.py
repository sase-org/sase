"""Focused bounds and best-effort tests for TUI telemetry sinks."""

from __future__ import annotations

import json
from pathlib import Path

from sase.logs import tui_telemetry


def test_agent_load_sink_rotates_under_explicit_byte_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "tui_agent_loads.jsonl"
    path.write_text('{"old":true}\n', encoding="utf-8")
    monkeypatch.setattr(tui_telemetry, "TUI_AGENT_LOADS_JSONL", str(path))
    monkeypatch.setenv(tui_telemetry.ENV_MAX_BYTES, "1")

    tui_telemetry.log_tui_agent_load({"new": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"new": True}
    assert json.loads(path.with_name(f"{path.name}.1").read_text()) == {"old": True}


def test_telemetry_write_failure_never_raises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    directory = tmp_path / "not-a-file"
    directory.mkdir()
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(directory))

    tui_telemetry.log_tui_stall({"diagnostic": "best effort"})
