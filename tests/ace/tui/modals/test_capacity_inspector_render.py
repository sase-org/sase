"""Tests for pure capacity inspector text renderers."""

from __future__ import annotations

from types import SimpleNamespace

from rich.cells import cell_len

from sase.ace.tui.modals._capacity_inspector_render import (
    empty_charged_message,
    middle_truncate,
    render_capacity_row,
    render_detail,
    render_facts,
    render_gauge,
    render_section_header,
    render_verdict,
)
from sase.core.runner_slots import capacity_view
from sase.project_display_names import ProjectDisplaySnapshot
from tests._runner_slots_helpers import _record
from tests.ace.tui.visual._capacity_inspector_fixtures import (
    busy_report,
    over_limit_report,
)
from tests.test_machine_capacity_report import (
    _report_from_records,
    _screenshot_records,
)


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


def test_capacity_rows_align_kind_and_age_across_name_lengths() -> None:
    short = render_capacity_row(
        mark="▰1",
        name="short",
        kind="worker-kind",
        note="n",
        age="3h12m",
        width=110,
    )
    long = render_capacity_row(
        mark="▰1",
        name="much-longer-worker-name",
        kind="worker-kind",
        note="explicit weight",
        age="50m",
        width=110,
    )

    assert short.plain.index("worker-kind") == long.plain.index("worker-kind")
    assert cell_len(short.plain) == 110
    assert cell_len(long.plain) == 110
    assert short.plain.endswith("3h12m")
    assert long.plain.endswith("50m")
    assert short.plain.index("worker-kind") > short.plain.index("short") + len("short")

    narrow_short = render_capacity_row(
        mark="▰1",
        name="short",
        kind="worker-kind",
        note="explicit weight",
        age="3h12m",
        width=80,
    )
    narrow_long = render_capacity_row(
        mark="▰1",
        name="much-longer-worker-name",
        kind="worker-kind",
        note="explicit weight",
        age="50m",
        width=80,
    )
    assert "worker-kind" not in narrow_short.plain
    assert cell_len(narrow_short.plain) == 80
    assert cell_len(narrow_long.plain) == 80
    assert narrow_short.plain.endswith("3h12m")
    assert narrow_long.plain.endswith("50m")


def test_capacity_row_fits_unicode_cell_widths() -> None:
    rendered = render_capacity_row(
        mark="▰2",
        name="α" * 24,
        kind="worker",
        note="inherited",
        age="18m",
        width=110,
    )

    assert cell_len(rendered.plain) <= 110
    assert "worker" in rendered.plain
    assert rendered.plain.endswith("18m")


def test_busy_facts_count_zero_weight_claims_and_riders() -> None:
    view = capacity_view(busy_report(), running_nodes=9)
    facts = render_facts(view)
    wrapped = render_facts(view, width=40)

    assert "9 running · 7 charged · 2 at 0" in facts.plain
    assert "9 running · 7 charged · 2 at 0" in wrapped.plain
    assert "\n" in wrapped.plain


def test_over_verdict_renders_title_and_detail_once() -> None:
    view = capacity_view(over_limit_report(), running_nodes=6)
    rendered = render_verdict(view)

    assert view.verdict is not None
    assert rendered.plain.count(view.verdict.title) == 1
    if view.verdict.detail:
        assert rendered.plain.count(view.verdict.detail) == 1
    if view.over_limit_note:
        assert view.over_limit_note not in rendered.plain


def test_empty_charged_message_is_unknown_when_accounting_is_invalid() -> None:
    valid = SimpleNamespace(admission_blocked=False, limit=8)
    blocked = SimpleNamespace(admission_blocked=True, limit=8)

    assert "all 8 units are free" in empty_charged_message(valid)
    assert empty_charged_message(blocked) == (
        "No known charged claims — free capacity is unknown"
    )


def test_rider_detail_uses_human_project_label_not_raw_key() -> None:
    parent = _record("/sess", run_started=True, agent_session="s1")
    child = _record("/sess2", run_started=True, agent_session="s1")
    view = capacity_view(_report_from_records([parent, child]))
    (rider,) = view.riders
    assert rider.project_key == "proj"

    rendered = render_detail(
        view=view,
        target_kind="rider",
        row=rider,
        group=None,
        snapshot=ProjectDisplaySnapshot({"proj": "Widgets"}),
    )

    assert "Widgets" in rendered.plain
    assert "proj" not in rendered.plain
    assert rendered.plain.count(" · ") >= 1
    assert rendered.plain.startswith(f"{rider.name} · rider · Widgets")
