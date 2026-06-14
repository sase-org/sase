"""Tests for the legacy dismissed-agent revive modal."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.models.agent_status import (
    STOPPED_COLOR,
    STOPPED_GLYPH,
    STOPPED_STATUS,
)
from sase.ace.tui.modals.revive_agent_modal import DismissedAgentSelectModal
from sase.ace.tui.modals.revive_agent_rendering import (
    format_agent_label,
    get_status_style,
)

from tests._agent_revive_helpers import make_agent


def test_modal_exposes_legacy_filter_placeholder_and_bindings() -> None:
    modal = DismissedAgentSelectModal(
        [make_agent(cl_name="alpha", raw_suffix="20260512120000")],
    )

    binding_actions = {
        binding.action if hasattr(binding, "action") else binding[1]
        for binding in modal.BINDINGS
    }

    assert "load_more" not in binding_actions
    assert "toggle_mark" in binding_actions
    assert "toggle_all" in binding_actions
    assert "PgDn" not in modal._hints_text()


def test_filter_matches_agent_label_and_response_content(tmp_path: Path) -> None:
    response_path = tmp_path / "response.md"
    response_path.write_text("Needle appears in the transcript.", encoding="utf-8")
    agent = make_agent(
        cl_name="alpha",
        raw_suffix="20260512120000",
        agent_name="named",
        response_path=str(response_path),
    )
    modal = DismissedAgentSelectModal([agent])
    modal._chat_contents[0] = response_path.read_text(encoding="utf-8").lower()

    assert modal._get_filtered_agents("named") == [(0, agent)]
    assert modal._get_filtered_agents("needle") == [(0, agent)]
    assert modal._get_filtered_agents("missing") == []


def test_marked_agents_return_original_order() -> None:
    first = make_agent(cl_name="alpha", raw_suffix="20260512120000")
    second = make_agent(cl_name="beta", raw_suffix="20260512120100")
    third = make_agent(cl_name="gamma", raw_suffix="20260512120200")
    modal = DismissedAgentSelectModal([first, second, third])
    modal._marked = {2, 0}

    assert modal._get_marked_agents() == [first, third]


def test_set_agents_recomputes_workflow_step_counts() -> None:
    parent = make_agent(cl_name="parent", raw_suffix="20260512120000")
    child = make_agent(
        cl_name="child",
        raw_suffix="20260512120100",
        parent_timestamp="20260512120000",
        step_index=1,
        step_type="agent",
    )
    modal = DismissedAgentSelectModal([])

    modal.agents = [parent]
    modal._all_dismissed = [parent, child]
    modal._step_counts = modal._compute_step_counts()

    assert modal._step_counts == {"20260512120000": 1}


def test_stopped_status_uses_canonical_style_and_glyph() -> None:
    agent = make_agent(status=STOPPED_STATUS)

    label = format_agent_label(agent)

    assert get_status_style(STOPPED_STATUS) == f"bold {STOPPED_COLOR}"
    assert f"{STOPPED_GLYPH} " in label.plain
    glyph_start = label.plain.index(STOPPED_GLYPH)
    glyph_end = glyph_start + len(STOPPED_GLYPH)
    assert any(
        span.start <= glyph_start
        and span.end >= glyph_end
        and str(span.style) == f"bold {STOPPED_COLOR}"
        for span in label.spans
    )
