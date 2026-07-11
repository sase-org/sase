"""Tests for saved dismissed-agent group revival rendering."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import sase.ace.tui.modals.saved_agent_group_revival_rendering as revival_rendering
from sase.ace.tui.models.agent_status import STOPPED_COLOR, STOPPED_STATUS
from sase.ace.tui.modals.saved_agent_group_revival_rendering import (
    _saved_group_time_label,
    _status_style,
    _title_with_top_level_count,
    build_saved_group_preview,
    format_saved_group_row,
)
from sase.core.agent_group_archive_wire import (
    SavedAgentGroupRefWire,
    SavedAgentGroupSummaryWire,
    SavedAgentGroupWire,
)

from .saved_agent_group_revival_modal_test_helpers import _group, _summary


def test_custom_search_preview_describes_recent_unscoped_filtering() -> None:
    text = build_saved_group_preview(None).plain

    assert "250 most recent dismissed agents" in text
    assert "filter them in the next panel" in text
    assert "scoped" not in text


def test_preview_rendering_includes_stable_time_and_status_text() -> None:
    text = build_saved_group_preview(
        _summary(0),
        _group("group-00"),
    ).plain

    assert "2 agents from backend" in text
    assert "Agents       3 (2 top-level)" in text
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

    assert "1 agent from backend" in text
    assert "Agents       2" in text
    assert "(1 top-level)" in text
    assert "root-worker" in text
    assert "prompt: Restore only the root worker." in text
    assert "child-worker" not in text
    assert "This child should be implicit." not in text


def test_preview_rendering_humanizes_saved_project_name_and_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = SavedAgentGroupSummaryWire(
        group_id="group-project-preview",
        created_at="2026-05-27T12:00:00Z",
        source="marked_agents",
        title="1 agent from backend",
        agent_count=1,
        top_level_agent_count=1,
        status_counts={"DONE": 1},
        project_names=("widgets",),
        cl_names=(),
    )
    group = SavedAgentGroupWire(
        group_id="group-project-preview",
        created_at="2026-05-27T12:00:00Z",
        source="marked_agents",
        title="1 agent from backend",
        agent_count=1,
        top_level_agent_count=1,
        status_counts={"DONE": 1},
        project_names=("widgets",),
        cl_names=(),
        agent_refs=(
            SavedAgentGroupRefWire(
                agent_type="run",
                cl_name="gh_acme__widgets",
                raw_suffix="20260527120000",
                display_name="gh_acme__widgets",
                status="DONE",
                prompt_preview="#gh:gh_acme__widgets Restore project.",
            ),
        ),
    )
    monkeypatch.setattr(
        revival_rendering,
        "project_display_name_for",
        lambda value: "widgets" if value == "gh_acme__widgets" else value,
    )
    monkeypatch.setattr(
        revival_rendering,
        "humanize_vcs_refs_in_text",
        lambda text: text.replace("gh_acme__widgets", "widgets"),
    )

    text = build_saved_group_preview(summary, group).plain

    assert "widgets" in text
    assert "#gh:widgets Restore project." in text
    assert "gh_acme__widgets" not in text


def test_named_preview_uses_name_with_generated_summary_context() -> None:
    text = build_saved_group_preview(
        _summary(0, name="Backend batch"),
        _group("group-00"),
    ).plain

    assert "Backend batch" in text
    assert "2 agents from backend" in text


def test_row_rendering_includes_compact_saved_time() -> None:
    text = format_saved_group_row(
        _summary(0),
        now=datetime(2026, 5, 27, 13, 30, tzinfo=UTC),
    ).plain

    assert "1h" in text
    assert "×2" in text
    assert "x1 ✓2" in text
    assert "05-27 12:00" not in text
    assert text.startswith("    1h  ×2")


def test_named_row_uses_name_with_generated_summary_context() -> None:
    text = format_saved_group_row(
        _summary(0, name="Backend batch"),
        now=datetime(2026, 5, 27, 13, 30, tzinfo=UTC),
    ).plain

    assert "Backend batch" in text
    assert "3 agents from backend" not in text


@pytest.mark.parametrize(
    ("title", "top_level_count", "expected"),
    (
        ("39 agents from @sase", 6, "6 agents from @sase"),
        ("2 agents in backend", 1, "1 agent in backend"),
        ("1 agent from sase", 2, "2 agents from sase"),
        ("8 agents across 3 PRs", 4, "4 agents across 3 PRs"),
        ("7 agents", 0, "0 agents"),
        ("6 agents from @sase", 6, "6 agents from @sase"),
        ("custom batch", 6, "custom batch"),
        ("agents from backend", 6, "agents from backend"),
    ),
)
def test_title_with_top_level_count_updates_generated_title_prefix(
    title: str,
    top_level_count: int,
    expected: str,
) -> None:
    assert _title_with_top_level_count(title, top_level_count) == expected


def test_saved_group_time_label_is_deterministic_with_supplied_now() -> None:
    label = _saved_group_time_label(
        "2026-05-27T12:00:00Z",
        now=datetime(2026, 5, 27, 13, 30, tzinfo=UTC),
    )

    assert label == "1h ago | 2026-05-27 12:00"


def test_stopped_status_uses_canonical_style() -> None:
    assert _status_style(STOPPED_STATUS) == f"bold {STOPPED_COLOR}"
