"""Tests for saved dismissed-agent group revival rendering."""

from __future__ import annotations

from datetime import UTC, datetime

from sase.ace.tui.models.agent_status import STOPPED_COLOR, STOPPED_STATUS
from sase.ace.tui.modals.saved_agent_group_revival_rendering import (
    _saved_group_time_label,
    _status_style,
    build_saved_group_preview,
    format_saved_group_row,
)
from sase.core.agent_group_archive_wire import (
    SavedAgentGroupRefWire,
    SavedAgentGroupSummaryWire,
    SavedAgentGroupWire,
)

from .saved_agent_group_revival_modal_test_helpers import _group, _summary


def test_preview_rendering_includes_stable_time_and_status_text() -> None:
    text = build_saved_group_preview(
        _summary(0),
        _group("group-00"),
    ).plain

    assert "3 agents from backend" in text
    assert "done:2" in text
    assert "failed:1" in text
    assert "worker-one" in text
    assert "codex/gpt-5" in text


def test_preview_rendering_shows_only_roots_with_prompt_preview() -> None:
    summary = SavedAgentGroupSummaryWire(
        group_id="group-root-preview",
        created_at="2026-05-27T12:00:00Z",
        source="marked_agents",
        title="2 agents from backend",
        agent_count=2,
        top_level_agent_count=1,
        status_counts={"DONE": 2},
        project_names=("sase",),
        cl_names=("backend",),
    )
    group = SavedAgentGroupWire(
        group_id="group-root-preview",
        created_at="2026-05-27T12:00:00Z",
        source="marked_agents",
        title="2 agents from backend",
        agent_count=2,
        top_level_agent_count=1,
        status_counts={"DONE": 2},
        project_names=("sase",),
        cl_names=("backend",),
        agent_refs=(
            SavedAgentGroupRefWire(
                agent_type="run",
                cl_name="backend",
                raw_suffix="20260527120000",
                display_name="root-worker",
                agent_name="backend.1",
                status="DONE",
                model="gpt-5",
                llm_provider="codex",
                prompt_preview="Restore only the root worker.",
            ),
            SavedAgentGroupRefWire(
                agent_type="workflow",
                cl_name="backend",
                raw_suffix="20260527120001",
                is_workflow_child=True,
                display_name="child-worker",
                agent_name="backend.child",
                status="DONE",
                prompt_preview="This child should be implicit.",
            ),
        ),
    )
    text = build_saved_group_preview(summary, group).plain

    assert "2 agents" in text
    assert "(1 top-level)" in text
    assert "root-worker" in text
    assert "prompt: Restore only the root worker." in text
    assert "child-worker" not in text
    assert "This child should be implicit." not in text


def test_named_preview_uses_name_with_generated_summary_context() -> None:
    text = build_saved_group_preview(
        _summary(0, name="Backend batch"),
        _group("group-00"),
    ).plain

    assert "Backend batch" in text
    assert "3 agents from backend" in text


def test_row_rendering_includes_compact_saved_time() -> None:
    text = format_saved_group_row(
        _summary(0),
        now=datetime(2026, 5, 27, 13, 30, tzinfo=UTC),
    ).plain

    assert "1h" in text
    assert "×3" in text
    assert "x1 ✓2" in text
    assert "05-27 12:00" not in text
    assert text.startswith("    1h  ×3")


def test_named_row_uses_name_with_generated_summary_context() -> None:
    text = format_saved_group_row(
        _summary(0, name="Backend batch"),
        now=datetime(2026, 5, 27, 13, 30, tzinfo=UTC),
    ).plain

    assert "Backend batch" in text
    assert "3 agents from backend" not in text


def test_saved_group_time_label_is_deterministic_with_supplied_now() -> None:
    label = _saved_group_time_label(
        "2026-05-27T12:00:00Z",
        now=datetime(2026, 5, 27, 13, 30, tzinfo=UTC),
    )

    assert label == "1h ago | 2026-05-27 12:00"


def test_stopped_status_uses_canonical_style() -> None:
    assert _status_style(STOPPED_STATUS) == f"bold {STOPPED_COLOR}"
