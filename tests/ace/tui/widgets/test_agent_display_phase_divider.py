"""Tests for agent display phase divider rendering."""

from __future__ import annotations

import re
from datetime import datetime

from sase.ace.tui.widgets.prompt_panel._agent_display_parts import render_phase_divider


class TestRenderPhaseDivider:
    def test_contains_label(self) -> None:
        divider = render_phase_divider("AGENT (plan)", datetime(2024, 1, 1, 14, 23, 45))
        assert "AGENT (plan)" in divider.plain

    def test_contains_time_format(self) -> None:
        divider = render_phase_divider("AGENT (code)", datetime(2024, 1, 1, 14, 23, 45))
        assert re.search(r"\d{2}:\d{2}:\d{2}", divider.plain)

    def test_none_start_time(self) -> None:
        divider = render_phase_divider("AGENT", None)
        assert "??:??:??" in divider.plain

    def test_bold_purple_label(self) -> None:
        divider = render_phase_divider("AGENT (plan)", datetime(2024, 1, 1))
        has_bold = any(
            "bold" in str(s.style) and "af87ff" in str(s.style).lower()
            for s in divider._spans
        )
        assert has_bold
