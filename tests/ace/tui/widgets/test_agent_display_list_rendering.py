"""Tests for agent display list and phase rendering."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_header_text,
    render_phase_divider,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent


class TestAgentListBeadBadge:
    def test_phase_agent_row_renders_bead_badge(self) -> None:
        agent = make_agent(agent_name="sase-x.3")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ @sase-x.3" in left.plain

    def test_land_agent_row_renders_epic_bead_badge(self) -> None:
        agent = make_agent(agent_name="sase-x.land")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ @sase-x.land" in left.plain

    def test_exact_land_agent_row_renders_epic_bead_badge(self) -> None:
        agent = make_agent(agent_name="sase-x")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ @sase-x" in left.plain

    def test_dismissed_phase_agent_row_renders_underlying_bead_badge(self) -> None:
        agent = make_agent(agent_name="260428.sase-x.3")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ @260428.sase-x.3" in left.plain

    def test_ordinary_agent_row_omits_bead_badge(self) -> None:
        agent = make_agent(agent_name="reviewer")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "◆" not in left.plain

    def test_dotted_ordinary_agent_row_omits_bead_badge(self) -> None:
        agent = make_agent(agent_name="aij.2")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "◆" not in left.plain
        assert "@aij.2" in left.plain

    def test_bead_badge_flows_from_fold_annotation_to_agent_name(self) -> None:
        agent = make_agent(agent_name="sase-x.3", tag="pinned")

        left, _, _ = format_agent_option(
            agent, 0, is_selected=False, fold_annotation="×3"
        )

        assert "(RUNNING)×3 ◆ @sase-x.3" in left.plain
        assert "@pinned" not in left.plain


class TestAwareWaitUntilRendering:
    def test_agent_row_renders_aware_wait_until_countdown(self) -> None:
        wait_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        agent = make_agent(status="WAITING", wait_until=wait_until)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "WAITING (until " in left.plain
        assert "," in left.plain

    def test_header_renders_aware_wait_until_countdown(self) -> None:
        wait_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        agent = make_agent(status="WAITING", wait_until=wait_until)

        header, _ = build_header_text(agent, cheap=True)

        assert "Waiting for: until " in header.plain
        assert " left)" in header.plain


# -- _render_phase_divider ----------------------------------------------------


class TestRenderPhaseDivider:
    def test_contains_label(self) -> None:
        divider = render_phase_divider("PLANNER", datetime(2024, 1, 1, 14, 23, 45))
        assert "PLANNER" in divider.plain

    def test_contains_time_format(self) -> None:
        divider = render_phase_divider("CODER", datetime(2024, 1, 1, 14, 23, 45))
        assert re.search(r"\d{2}:\d{2}:\d{2}", divider.plain)

    def test_none_start_time(self) -> None:
        divider = render_phase_divider("AGENT", None)
        assert "??:??:??" in divider.plain

    def test_bold_purple_label(self) -> None:
        divider = render_phase_divider("PLANNER", datetime(2024, 1, 1))
        has_bold = any(
            "bold" in str(s.style) and "af87ff" in str(s.style).lower()
            for s in divider._spans
        )
        assert has_bold


# -- followup_agents field -----------------------------------------------------
