"""Tests for the Agents-tab machine-labelled cap chip."""

from __future__ import annotations

import math
from unittest.mock import patch

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.models._agent_runner_slot_types import RunnerCapacityHolder
from sase.ace.tui.widgets.agent_load_indicator import (
    AgentLoadIndicator,
    _agent_load_tooltip,
    _build_agent_load_text,
    _format_load_value,
    _override_marks,
)
from sase.ace.tui.widgets._usage_indicator_palette import (
    usage_percent_color,
    usage_rejected_style,
    usage_zero_value_style,
)
from sase.config.runner_limit_override import (
    EffectiveRunnerLimitSnapshot,
    TemporaryRunnerLimitOverride,
)


_ATHENA = "athena"
_NOW = 1_700_000_000.0


def _text(
    limit: float,
    occupied: float | None,
    *,
    dark: bool = True,
    density: str = "full",
    **kwargs: object,
) -> Text:
    return _build_agent_load_text(
        limit,
        occupied,
        dark=dark,
        density=density,  # type: ignore[arg-type]
        machine_label=_ATHENA,
        **kwargs,  # type: ignore[arg-type]
    )


def _value_style(text: Text, value: str) -> str:
    start = text.plain.index(value)
    covering = [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= start + len(value)
    ]
    assert covering, f"no style for {value!r} in {text.plain!r}"
    return covering[-1]


def _override(
    *,
    created_at: float,
    expires_at: float | None = None,
    limit: int = 8,
) -> EffectiveRunnerLimitSnapshot:
    return EffectiveRunnerLimitSnapshot(
        configured_limit=10,
        temporary_override=TemporaryRunnerLimitOverride(
            version=1,
            limit=limit,
            created_at=created_at,
            expires_at=expires_at,
            source="ace",
        ),
        captured_at=_NOW,
    )


def test_format_load_value_table() -> None:
    assert _format_load_value(3.0) == "3"
    assert _format_load_value(10) == "10"
    assert _format_load_value(2.5) == "2.5"
    assert _format_load_value(0.1 + 0.2) == "0.3"
    assert _format_load_value(1 / 3) == "0.33"
    assert _format_load_value(9.999) == "10"
    assert _format_load_value(0.75) == "0.75"
    assert _format_load_value(3.33) == "3.33"
    assert _format_load_value(-0.001) == "0"
    assert _format_load_value(None) == "—"
    assert _format_load_value(float("nan")) == "—"
    assert _format_load_value(float("inf")) == "—"
    assert _format_load_value(True) == "—"
    assert _format_load_value("7") == "—"


def test_style_mapping_capacity_ten_loads_zero_to_nine() -> None:
    expected_dark = [
        "#65C3ED",
        "#48CCD0",
        "#4CD4B0",
        "#78DB8D",
        "#AADC64",
        "#CED44C",
        "#EBC04F",
        "#FFA552",
        "#FF805F",
        "#FF5F6D",
    ]
    for dark in (True, False):
        colors: list[str] = []
        for load in range(10):
            text = _text(10.0, float(load), dark=dark, source="authoritative")
            value = f"{_format_load_value(float(load))}/10"
            style = _value_style(text, value)
            colors.append(style)
            free = round(max(0.0, 10.0 - float(load)) / 10.0 * 100.0, 6)
            assert style == f"bold {usage_percent_color(free, dark=dark)}"
        assert len(set(colors)) == 10
    dark_colors = [
        _value_style(
            _text(10.0, float(load), dark=True, source="authoritative"),
            f"{load}/10",
        )
        for load in range(10)
    ]
    assert dark_colors == [f"bold {color}" for color in expected_dark]


def test_at_and_over_capacity_uses_inverted_chip() -> None:
    for occupied in (10.0, 12.0, 9.999):
        for dark in (True, False):
            text = _text(10.0, occupied, dark=dark, source="authoritative")
            value = f"{_format_load_value(occupied)}/10"
            assert value in text.plain
            assert _value_style(text, value) == usage_zero_value_style(dark=dark)
    text = _text(10.0, 9.99, dark=True, source="authoritative")
    assert "9.99/10" in text.plain
    covering = _value_style(text, "9.99/10")
    assert covering != usage_zero_value_style(dark=True)
    assert "FF5F6D" in covering


def test_float_noise_lands_in_expected_bucket() -> None:
    text = _text(10.0, 5.9, dark=True, source="authoritative")
    assert _value_style(text, "5.9/10") == (
        f"bold {usage_percent_color(41.0, dark=True)}"
    )

    text = _text(1.0, 0.1 + 0.2, dark=True, source="authoritative")
    assert "0.3/1" in text.plain
    assert _value_style(text, "0.3/1") == (
        f"bold {usage_percent_color(70.0, dark=True)}"
    )


def test_placeholder_states_are_dim() -> None:
    text = _text(0.0, None, dark=True, source="authoritative")
    assert text.plain == "⌂athena cap —/— · "
    assert all(str(span.style) == "dim" for span in text.spans)

    text = _text(10.0, None, dark=True, source="authoritative")
    assert text.plain == "⌂athena cap —/10 · "
    assert _value_style(text, "—/10") == "dim"


def test_one_style_span_covers_value_run_and_chrome_is_dim() -> None:
    text = _text(10.0, 7.0, dark=True, source="authoritative")
    assert text.plain == "⌂athena cap 7/10 · "
    value = "7/10"
    start = text.plain.index(value)
    covering = [
        span
        for span in text.spans
        if span.start <= start and span.end >= start + len(value)
    ]
    assert len(covering) == 1
    assert "/" in text.plain[start : start + len(value)]
    assert str(text.spans[0].style) == "dim"
    assert text.plain.startswith("⌂athena cap ")
    assert str(text.spans[-1].style) == "dim"


def test_full_keeps_machine_label_compact_keeps_cap() -> None:
    full = _text(10.0, 7.0, dark=True, density="full", source="authoritative")
    compact = _text(10.0, 7.0, dark=True, density="compact", source="authoritative")
    assert full.plain == "⌂athena cap 7/10 · "
    assert compact.plain == "cap 7/10 · "
    assert compact.plain.startswith("cap ")
    assert "7/10" in compact.plain
    assert cell_len(full.plain) - cell_len(compact.plain) == cell_len("⌂athena ")

    gauge = AgentLoadIndicator()
    gauge._limit = 10.0
    gauge._occupied = 7.0
    gauge._machine_label = _ATHENA
    gauge._source = "authoritative"
    assert gauge.full_cells - gauge.compact_cells == cell_len("⌂athena ")


def test_chip_states_match_plan_examples() -> None:
    full = _text(8.0, 5.0, source="authoritative", override_active=True)
    assert full.plain == "⌂athena cap 5/8* · "

    compact = _text(
        8.0, 5.0, density="compact", source="authoritative", override_active=True
    )
    assert compact.plain == "cap 5/8* · "

    estimate = _text(8.0, 5.0, source="estimate")
    assert estimate.plain == "⌂athena cap ~5/8 · "

    stale = _text(8.0, 5.0, source="authoritative", report_age_seconds=41)
    assert stale.plain == "⌂athena cap 5/8 ⟳41s · "

    fault = _text(8.0, None, source="authoritative", accounting_valid=False)
    assert fault.plain == "⌂athena cap ?/8 ! · "
    assert _value_style(fault, "?/8") == usage_zero_value_style(dark=True)
    assert usage_rejected_style(dark=True) in {str(span.style) for span in fault.spans}

    over = _text(8.0, 8.25, source="authoritative", over_limit=True)
    assert over.plain == "⌂athena cap 8.25/8 ▲ · "
    assert "▲" in over.plain
    assert _value_style(over, "8.25/8") == usage_zero_value_style(dark=True)


def test_fault_never_renders_free_capacity_color() -> None:
    text = _text(8.0, None, source="authoritative", accounting_valid=False)
    style = _value_style(text, "?/8")
    assert style == usage_zero_value_style(dark=True)
    assert "65C3ED" not in style
    assert "48CCD0" not in style
    assert "4CD4B0" not in style


def test_tooltip_strings_for_all_states() -> None:
    gauge = AgentLoadIndicator()
    with patch.object(gauge, "update"):
        gauge.update_load(10.0, 7.0, machine_label=_ATHENA, source="authoritative")
        assert "7 of 10 units in use · 3 headroom" in gauge.tooltip
        assert ",l opens the capacity inspector" in gauge.tooltip
        gauge.update_load(10.0, 10.0, machine_label=_ATHENA, source="authoritative")
        assert "10 of 10 units in use · 0 headroom" in gauge.tooltip
        gauge.update_load(10.0, None, machine_label=_ATHENA, source="authoritative")
        assert "cap unavailable · limit 10" in gauge.tooltip
        gauge.update_load(0.0, None, machine_label=_ATHENA)
        assert gauge.tooltip == "Runner capacity has not loaded yet."


def test_tooltip_lists_holders_with_weights_and_kinds() -> None:
    holders = (
        RunnerCapacityHolder(label="0xe--mon-1", weight=1.0, kind="monitor"),
        RunnerCapacityHolder(label="research.3r.cdx", weight=0.25, kind=None),
    )
    tooltip = _agent_load_tooltip(8.0, 1.25, holders, source="authoritative")

    assert "1.25 of 8 units in use" in tooltip
    assert "Held by:" in tooltip
    assert "• 0xe--mon-1 (monitor): 1" in tooltip
    assert "• research.3r.cdx: 0.25" in tooltip
    assert ",l opens the capacity inspector" in tooltip


def test_tooltip_caps_holders_with_more_count() -> None:
    holders = tuple(
        RunnerCapacityHolder(label=f"agent-{index:02d}", weight=1.0, kind=None)
        for index in range(14)
    )
    tooltip = _agent_load_tooltip(20.0, 14.0, holders, source="authoritative")

    assert tooltip.count("• ") == 12
    assert "… +2 more" in tooltip


def test_tooltip_running_versus_cap_and_remote_note() -> None:
    holders = (
        RunnerCapacityHolder(label="a", weight=1.0),
        RunnerCapacityHolder(label="b", weight=1.0),
        RunnerCapacityHolder(label="c", weight=1.0),
        RunnerCapacityHolder(label="d", weight=1.0),
        RunnerCapacityHolder(label="e", weight=1.0),
        RunnerCapacityHolder(label="cutover", weight=0.0, kind="monitor"),
    )
    tooltip = _agent_load_tooltip(
        8.0,
        5.0,
        holders,
        source="authoritative",
        running_nodes=6,
        remote_tab=True,
    )
    assert "6 running nodes · 5 hold capacity (5) · 1 holds 0" in tooltip
    assert _REMOTE_NOTE_SNIPPET in tooltip


_REMOTE_NOTE_SNIPPET = (
    "This chip is this machine's capacity; remote capacity is not shown."
)


def test_tooltip_fault_names_subtotal_and_admission_blocked() -> None:
    tooltip = _agent_load_tooltip(
        8.0,
        None,
        source="authoritative",
        accounting_valid=False,
        known_occupied=5.0,
        diagnostics=("invalid-weight: live claim weight is not finite",),
    )
    assert "Known subtotal: 5" in tooltip
    assert "invalid-weight: live claim weight is not finite" in tooltip
    assert "admission blocked" in tooltip


def test_tooltip_overage_names_per_launch_budgets() -> None:
    tooltip = _agent_load_tooltip(8.0, 8.25, source="authoritative", over_limit=True)
    assert "%queue(capacity=N)" in tooltip


def test_update_load_noop_and_fit_requests() -> None:
    gauge = AgentLoadIndicator()
    with patch.object(gauge, "update"):
        gauge.update_load(10.0, 0.0, machine_label=_ATHENA)
        with patch.object(gauge, "update") as mock_update:
            gauge.update_load(10.0, 0.0, machine_label=_ATHENA)
        mock_update.assert_not_called()

    gauge = AgentLoadIndicator()
    with patch.object(gauge, "update"):
        gauge.update_load(10.0, 0.0, machine_label=_ATHENA)
        with patch.object(gauge, "_request_host_fit") as mock_fit:
            gauge.update_load(10.0, 1.0, machine_label=_ATHENA)
        mock_fit.assert_not_called()
    gauge = AgentLoadIndicator()
    with patch.object(gauge, "update"):
        gauge.update_load(10.0, 0.0, machine_label=_ATHENA)
        with patch.object(gauge, "_request_host_fit") as mock_fit:
            gauge.update_load(100.0, 0.0, machine_label=_ATHENA)
        mock_fit.assert_called_once()


def test_update_load_retains_authoritative_report_context_for_later_chip_rendering() -> (
    None
):
    gauge = AgentLoadIndicator()
    provenance = object()
    with patch.object(gauge, "update"):
        gauge.update_load(
            8.0,
            5.0,
            source="authoritative",
            report_age_seconds=2.5,
            accounting_valid=True,
            over_limit=False,
            scan_current=True,
            limit_provenance=provenance,
            machine_label=_ATHENA,
        )

    assert _text(8.0, 5.0, dark=True, source="authoritative").plain == (
        "⌂athena cap 5/8 · "
    )
    assert gauge._source == "authoritative"
    assert gauge._report_age_seconds == 2.0
    assert gauge._accounting_valid is True
    assert gauge._over_limit is False
    assert gauge._scan_current is True
    assert gauge._limit_provenance is provenance
    assert gauge._machine_label == _ATHENA


def test_override_set_cleared_expired_flip_within_one_refresh() -> None:
    gauge = AgentLoadIndicator()
    active = _override(created_at=_NOW - 60.0)
    expired = _override(created_at=_NOW - 60.0, expires_at=_NOW - 1.0)
    with patch.object(gauge, "update"):
        gauge.update_load(
            8.0,
            5.0,
            source="authoritative",
            limit_provenance=active,
            machine_label=_ATHENA,
            now=_NOW,
        )
        assert gauge._override_active is True
        assert gauge._override_warning is False
        gauge.update_load(
            8.0,
            5.0,
            source="authoritative",
            limit_provenance=None,
            machine_label=_ATHENA,
            now=_NOW,
        )
        assert gauge._override_active is False
        gauge.update_load(
            8.0,
            5.0,
            source="authoritative",
            limit_provenance=expired,
            machine_label=_ATHENA,
            now=_NOW,
        )
        assert gauge._override_active is False


def test_override_without_expiry_older_than_14_days_uses_warning_style() -> None:
    fresh = _override(created_at=_NOW - 60.0)
    stale = _override(created_at=_NOW - (15 * 24 * 3600))
    assert _override_marks(fresh, now=_NOW) == (True, False)
    assert _override_marks(stale, now=_NOW) == (True, True)
    text = _text(
        8.0,
        5.0,
        source="authoritative",
        override_active=True,
        override_warning=True,
    )
    star_at = text.plain.index("*")
    covering = [
        str(span.style) for span in text.spans if span.start <= star_at < span.end
    ]
    assert covering
    assert "EBC04F" in covering[-1]


def test_set_density_only_repaints_on_change_and_never_refits() -> None:
    gauge = AgentLoadIndicator(density="full")
    with patch.object(gauge, "update"):
        assert gauge.set_density("full") is False
        with patch.object(gauge, "_request_host_fit") as mock_fit:
            assert gauge.set_density("compact") is True
            assert gauge.density == "compact"
        mock_fit.assert_not_called()
        with patch.object(gauge, "_request_host_fit") as mock_fit:
            assert gauge.set_density("compact") is False
        mock_fit.assert_not_called()


def test_render_path_does_not_read_runner_configuration() -> None:
    gauge = AgentLoadIndicator()
    with (
        patch(
            "sase.config.core.get_max_running_agents",
            side_effect=AssertionError("render path read configuration"),
        ),
        patch.object(gauge, "update"),
    ):
        gauge.update_load(10.0, 7.0, machine_label=_ATHENA)
        _text(10.0, 7.0, dark=True, density="full", source="authoritative")
        _text(10.0, 7.0, dark=True, density="compact", source="authoritative")
        assert gauge.full_cells > 0
        assert gauge.compact_cells > 0
        assert gauge.content_cells > 0
        assert math.isfinite(gauge.full_cells)


def test_tooltip_uses_shared_view_for_screenshot_shape() -> None:
    from tests.test_machine_capacity_report import (
        _report_from_records,
        _screenshot_records,
    )

    report = _report_from_records(_screenshot_records())
    tooltip = _agent_load_tooltip(
        8.0,
        5.0,
        source="authoritative",
        running_nodes=6,
        report=report,
    )
    assert "5 of 8 units in use · 3 headroom" in tooltip
    assert "6 running nodes" in tooltip
    assert "hold capacity" in tooltip
    assert "holds 0" in tooltip
    assert "ACE override" in tooltip
    assert ",l opens the capacity inspector" in tooltip


def test_help_reference_covers_cap_versus_running() -> None:
    from sase.ace.tui.keymaps import KeymapRegistry
    from sase.ace.tui.modals.help_modal.agents_reference_sections import (
        reference_sections,
    )
    from tests._keymaps_helpers import default_app_keymaps

    sections = reference_sections(KeymapRegistry(app=default_app_keymaps()))
    hay = "\n".join(f"{title} {row}" for title, rows in sections for row in rows)
    assert "Capacity" in hay
    assert "cap N/M" in hay
    assert "This machine's runner capacity" in hay
    assert "Running-bucket node count" in hay
    assert "Share one claim; waits hold 0" in hay
