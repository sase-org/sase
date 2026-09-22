"""Tests for the Agents-tab runner load gauge."""

from __future__ import annotations

import math
from unittest.mock import patch

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets.agent_load_indicator import (
    AgentLoadIndicator,
    _build_agent_load_text,
    _format_load_value,
)
from sase.ace.tui.widgets._usage_indicator_palette import (
    usage_percent_color,
    usage_zero_value_style,
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
            text = _build_agent_load_text(10.0, float(load), dark=dark, density="full")
            value = f"{_format_load_value(float(load))}/10"
            start = text.plain.index(value)
            styles = {
                str(span.style)
                for span in text.spans
                if span.start <= start and span.end >= start + len(value)
            }
            assert styles, f"no style for load {load} dark={dark}"
            style = next(iter(styles)) if len(styles) == 1 else None
            assert style is not None, f"split style for load {load} dark={dark}"
            colors.append(style)
            free = round(max(0.0, 10.0 - float(load)) / 10.0 * 100.0, 6)
            assert style == f"bold {usage_percent_color(free, dark=dark)}"
        assert len(set(colors)) == 10
    dark_colors = [
        _build_agent_load_text(10.0, float(load), dark=True, density="full")
        .spans[1]
        .style
        for load in range(10)
    ]
    assert [str(style) for style in dark_colors] == [
        f"bold {color}" for color in expected_dark
    ]


def test_at_and_over_capacity_uses_inverted_chip() -> None:
    for occupied in (10.0, 12.0, 9.999):
        for dark in (True, False):
            text = _build_agent_load_text(10.0, occupied, dark=dark, density="full")
            value = f"{_format_load_value(occupied)}/10"
            assert value in text.plain
            start = text.plain.index(value)
            covering = [
                str(span.style)
                for span in text.spans
                if span.start <= start and span.end >= start + len(value)
            ]
            assert covering
            assert covering[-1] == usage_zero_value_style(dark=dark)
    # Just below capacity stays a red foreground, not the chip.
    text = _build_agent_load_text(10.0, 9.99, dark=True, density="full")
    assert "9.99/10" in text.plain
    start = text.plain.index("9.99/10")
    covering = [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= start + len("9.99/10")
    ]
    assert covering
    assert covering[-1] != usage_zero_value_style(dark=True)
    assert "FF5F6D" in covering[-1]


def test_float_noise_lands_in_expected_bucket() -> None:
    text = _build_agent_load_text(10.0, 5.9, dark=True, density="full")
    start = text.plain.index("5.9/10")
    covering = [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= start + len("5.9/10")
    ]
    assert covering
    assert covering[-1] == f"bold {usage_percent_color(41.0, dark=True)}"

    text = _build_agent_load_text(1.0, 0.1 + 0.2, dark=True, density="full")
    assert "0.3/1" in text.plain
    start = text.plain.index("0.3/1")
    covering = [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= start + len("0.3/1")
    ]
    assert covering
    assert covering[-1] == f"bold {usage_percent_color(70.0, dark=True)}"


def test_placeholder_states_are_dim() -> None:
    text = _build_agent_load_text(0.0, None, dark=True, density="full")
    assert text.plain == "load: —/— · "
    assert all(str(span.style) == "dim" for span in text.spans)

    text = _build_agent_load_text(10.0, None, dark=True, density="full")
    assert text.plain == "load: —/10 · "
    start = text.plain.index("—/10")
    covering = [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= start + len("—/10")
    ]
    assert covering == ["dim"]


def test_one_style_span_covers_value_run_and_chrome_is_dim() -> None:
    text = _build_agent_load_text(10.0, 7.0, dark=True, density="full")
    assert text.plain == "load: 7/10 · "
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
    assert text.plain.startswith("load: ")
    assert str(text.spans[-1].style) == "dim"


def test_full_vs_compact_density_widths() -> None:
    full = _build_agent_load_text(10.0, 7.0, dark=True, density="full")
    compact = _build_agent_load_text(10.0, 7.0, dark=True, density="compact")
    assert full.plain == "load: 7/10 · "
    assert compact.plain == "7/10 · "
    assert cell_len(full.plain) - cell_len(compact.plain) == len("load: ")

    gauge = AgentLoadIndicator()
    gauge._limit = 10.0
    gauge._occupied = 7.0
    assert gauge.full_cells - gauge.compact_cells == len("load: ")


def test_tooltip_strings_for_all_states() -> None:
    gauge = AgentLoadIndicator()
    with patch.object(gauge, "update"):
        gauge.update_load(10.0, 7.0)
        assert gauge.tooltip == (
            "Runner load: 7 of 10 capacity units in use (3 free).\n"
            "New agents queue when load reaches capacity."
        )
        gauge.update_load(10.0, 10.0)
        assert gauge.tooltip == (
            "Runner load: 10 of 10 capacity units in use (at capacity).\n"
            "New agents queue until capacity frees up."
        )
        gauge.update_load(10.0, None)
        assert gauge.tooltip == "Runner load is unavailable; capacity is 10 units."
        gauge.update_load(0.0, None)
        assert gauge.tooltip == "Runner capacity has not loaded yet."


def test_update_load_noop_and_fit_requests() -> None:
    gauge = AgentLoadIndicator()
    with patch.object(gauge, "update"):
        gauge.update_load(10.0, 0.0)
        with patch.object(gauge, "update") as mock_update:
            gauge.update_load(10.0, 0.0)
        mock_update.assert_not_called()

    gauge = AgentLoadIndicator()
    with patch.object(gauge, "update"):
        gauge.update_load(10.0, 0.0)
        # Same width (single-digit loads) changes content but not width: no refit.
        with patch.object(gauge, "_request_host_fit") as mock_fit:
            gauge.update_load(10.0, 1.0)
        mock_fit.assert_not_called()
    gauge = AgentLoadIndicator()
    with patch.object(gauge, "update"):
        gauge.update_load(10.0, 0.0)
        # Width change (1 digit to 2 digits with label) requests a host fit.
        with patch.object(gauge, "_request_host_fit") as mock_fit:
            gauge.update_load(100.0, 0.0)
        mock_fit.assert_called_once()


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
        gauge.update_load(10.0, 7.0)
        _build_agent_load_text(10.0, 7.0, dark=True, density="full")
        _build_agent_load_text(10.0, 7.0, dark=True, density="compact")
        assert gauge.full_cells > 0
        assert gauge.compact_cells > 0
        assert gauge.content_cells > 0
        assert math.isfinite(gauge.full_cells)
