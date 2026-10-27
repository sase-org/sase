"""Tests for pure capacity inspector text renderers."""

from __future__ import annotations

from sase.ace.tui.modals._capacity_inspector_render import (
    middle_truncate,
    render_capacity_row,
    render_gauge,
    render_section_header,
)
from tests.test_machine_capacity_report import (
    _report_from_records,
    _screenshot_records,
)
from sase.core.runner_slots import capacity_view


def test_middle_truncation_preserves_name_head_and_tail_by_cell_width() -> None:
    value = "bob-cli-an.6.6.6.5.6.5.5.6.6.6.6.6.land"
    rendered = middle_truncate(value, 24)

    assert rendered.startswith("bob-cli-an")
    assert rendered.endswith(".6.6.6.land")
    assert "…" in rendered


def test_capacity_row_drops_kind_at_narrow_breakpoint() -> None:
    wide = render_capacity_row(
        mark="▰2",
        name="alpha-with-a-long-name",
        kind="worker-kind",
        note="explicit weight",
        age="3h12m",
        width=110,
    )
    narrow = render_capacity_row(
        mark="▰2",
        name="alpha-with-a-long-name",
        kind="worker-kind",
        note="explicit weight",
        age="3h12m",
        width=80,
    )

    assert "worker-kind" in wide.plain
    assert "worker-kind" not in narrow.plain
    assert "explicit weight" in narrow.plain
    assert len(narrow.plain) <= 80


def test_gauge_highlight_colors_the_selected_owner_span() -> None:
    report = _report_from_records(_screenshot_records())
    view = capacity_view(report, running_nodes=6)

    gauge = render_gauge(
        view,
        width=36,
        highlighted_owner=0,
        dark=True,
        accent="#ABCDEF",
    )

    assert "█" in gauge.plain
    assert any("ABCDEF" in str(span.style).upper() for span in gauge.spans)


def test_section_header_fills_rule_and_right_aligns_summary() -> None:
    rendered = render_section_header("Using capacity", "8 units · 7 agents", width=80)

    assert rendered.plain.startswith("USING CAPACITY")
    assert "─" in rendered.plain
    assert rendered.plain.endswith("8 units · 7 agents")
    assert len(rendered.plain) == 80
