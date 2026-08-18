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

    def test_default_accent_is_purple(self) -> None:
        divider = render_phase_divider("AGENT (code)", datetime(2024, 1, 1, 13, 0, 0))
        styles = [str(span.style).lower() for span in divider._spans]
        assert any("bold" in style and "af87ff" in style for style in styles)
        assert "⚙" not in divider.plain

    def test_accent_and_glyph_render_before_label(self) -> None:
        divider = render_phase_divider(
            "MONITOR",
            datetime(2024, 1, 1, 13, 1, 0),
            accent="#FFAF5F",
            glyph="⚙",
        )
        assert "⚙ MONITOR" in divider.plain
        glyph_start = divider.plain.index("⚙")
        label_start = divider.plain.index("MONITOR")
        assert glyph_start < label_start
        has_accent = any(
            "bold" in str(span.style) and "ffaf5f" in str(span.style).lower()
            for span in divider._spans
        )
        assert has_accent
