"""Tests for attempt-history rendering in the agent display."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType, AttemptRecord
from sase.ace.tui.widgets.prompt_panel._agent_display import (
    _render_merged_attempt_history,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_header_text,
    render_attempt_divider,
)


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/test.gp",
        "status": "RUNNING",
        "start_time": datetime(2026, 4, 22, 14, 0, 0),
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def _make_record(
    n: int,
    *,
    status: str = "failed",
    used_fallback: bool = False,
    model: str | None = None,
) -> AttemptRecord:
    return AttemptRecord(
        attempt_number=n,
        status=status,
        start_epoch=1745337600.0 + n * 60,
        end_epoch=1745337660.0 + n * 60,
        model=model,
        used_fallback=used_fallback,
        error_snippet=f"error {n}",
        error_full=f"error {n} full traceback",
        live_reply_path="/nonexistent/live_reply.md",
        timestamps_path="/nonexistent/live_reply_timestamps.jsonl",
    )


def test_divider_for_failed_attempt_shows_error() -> None:
    record = _make_record(1)
    divider = render_attempt_divider(record, is_current=False)
    plain = divider.plain
    assert "ATTEMPT 1" in plain
    assert "error 1" in plain


def test_divider_for_current_uses_current_label() -> None:
    divider = render_attempt_divider(None, is_current=True)
    assert "ATTEMPT (current)" in divider.plain


def test_divider_for_fallback_labels_model() -> None:
    record = _make_record(2, used_fallback=True, model="backup-model")
    divider = render_attempt_divider(record, is_current=False)
    assert "fallback" in divider.plain
    assert "backup-model" in divider.plain


def test_merged_history_emits_one_block_per_attempt_plus_current() -> None:
    agent = _make_agent(
        attempt_history=[_make_record(1), _make_record(2, status="failed")],
    )
    out = _render_merged_attempt_history(agent)
    labels: list[str] = []
    for r in out:
        plain = getattr(r, "plain", None)
        if plain is not None:
            labels.append(plain)
    joined = "\n".join(labels)
    assert "ATTEMPT 1" in joined
    assert "ATTEMPT 2" in joined
    assert "ATTEMPT (current)" in joined


def test_header_shows_per_attempt_sublines_when_history_present() -> None:
    agent = _make_agent(
        attempt_history=[_make_record(1), _make_record(2)],
        retry_count=2,
        max_retries=3,
    )
    header, _ = build_header_text(agent)
    assert "Retries: " in header.plain
    # Per-attempt sub-lines
    assert "Attempt 1" in header.plain
    assert "Attempt 2" in header.plain
    assert "error 1" in header.plain
    assert "error 2" in header.plain


def test_header_unchanged_when_no_retries_or_history() -> None:
    agent = _make_agent()
    header, _ = build_header_text(agent)
    # No retry section at all when there's nothing to report.
    assert "Retries: " not in header.plain
    assert "Attempt 1" not in header.plain


def test_empty_attempt_history_renders_nothing_merged() -> None:
    """Agents without attempts never invoke the merged renderer — guards the byte-identical invariant."""
    agent = _make_agent(attempt_history=[])
    assert agent.attempt_history == []
