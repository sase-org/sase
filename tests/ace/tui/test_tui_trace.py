"""Unit tests for the SASE_TUI_TRACE span recorder.

Bead sase-w.1 / sdd/tales/202604/tui_perf_overhaul_1.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.util import trace


@pytest.fixture(autouse=True)
def _reset_context() -> None:
    """Each test starts with a clean global trace context."""
    trace._context.clear()


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_disabled_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No env flag → no JSONL writes."""
    log = tmp_path / "trace.jsonl"
    monkeypatch.delenv("SASE_TUI_TRACE", raising=False)
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))

    with trace.tui_trace("phase.demo", count=42):
        pass

    assert not log.exists()


def test_enabled_writes_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SASE_TUI_TRACE=1 → one line per span with required fields."""
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))

    with trace.tui_trace("phase.demo", count=42):
        pass

    rows = _records(log)
    assert len(rows) == 1
    row = rows[0]
    assert row["span"] == "phase.demo"
    assert row["count"] == 42
    assert isinstance(row["duration_ms"], (int, float))
    assert row["duration_ms"] >= 0.0
    assert "ts" in row
    assert row["current_tab"] is None


def test_global_context_merges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``set_trace_context`` fields appear on every emitted span."""
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))

    trace.set_trace_context(current_tab="agents", current_idx=7)
    with trace.tui_trace("agents.refresh"):
        pass

    rows = _records(log)
    assert len(rows) == 1
    assert rows[0]["current_tab"] == "agents"
    assert rows[0]["current_idx"] == 7


def test_per_call_kwargs_override_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kwargs at the call site win over global context for the same key."""
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))

    trace.set_trace_context(current_idx=1, count=999)
    with trace.tui_trace("phase.demo", count=3):
        pass

    rows = _records(log)
    # current_idx came from context; count was overridden by kwargs.
    assert rows[0]["current_idx"] == 1
    assert rows[0]["count"] == 3


def test_nested_spans_each_emit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nested ``tui_trace`` blocks each produce one record."""
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))

    with trace.tui_trace("outer"):
        with trace.tui_trace("inner"):
            pass

    rows = _records(log)
    span_names = [r["span"] for r in rows]
    # Inner closes first, so it's written first.
    assert span_names == ["inner", "outer"]


def test_set_trace_context_none_clears_field() -> None:
    """Passing ``None`` to set_trace_context drops the field."""
    trace.set_trace_context(current_tab="agents")
    assert trace._context["current_tab"] == "agents"
    trace.set_trace_context(current_tab=None)
    assert "current_tab" not in trace._context
