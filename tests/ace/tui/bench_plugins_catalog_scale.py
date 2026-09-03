"""Scale bench for the Updates > Plugins sub-tab.

Run explicitly with::

    pytest -s -m slow tests/ace/tui/bench_plugins_catalog_scale.py

The harness stubs the catalog at ``_load_plugins_catalog`` (the same seam
the functional pane tests use), then records p50/p95/max for pane open, one
settled filter keystroke, 20 j presses driven through the queued
``OptionHighlighted`` handler, ``'`` jump-hint allocation, and one ``I``
install-mark toggle. Filter match count is held at 100 rows (or the full
catalog when it is smaller) so the curve does not invert when *n* grows.

The filter keystroke scenario drives the real ``on_input_changed`` path and
then fires its debounced rebuild synchronously (instead of waiting out the
real timer) so the sample reflects the settled-filter cost the debouncer
pays once per typing burst, not the (now near-zero) cost of scheduling it.

Phase ``guard`` enforces filter-keystroke and j-press p95 under
:data:`TARGET_P95_MS` at every catalog size, including n=2000.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import pytest
from textual.widgets import Input, OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane
from tests.ace.tui._plugins_browser_pane_helpers import (
    _open_plugins_pane,
    _patch_catalog,
    _patch_other_panes,
    _uv_tool,
)
from tests.perf.plugin_catalog_scale import (
    CATALOG_SCALE_SIZES,
    FILTER_KEYSTROKE,
    TARGET_P95_MS,
    make_scale_catalog,
    merge_baseline_section,
    scale_filter_match_count,
    summarize_ms,
)

pytestmark = pytest.mark.slow

_PANE_OPEN_SAMPLES = 5
_PANE_OPEN_WARMUP = 1
_FILTER_SAMPLES = 6
_FILTER_WARMUP = 1
_J_PRESSES = 20
_JUMP_SAMPLES = 4
_JUMP_WARMUP = 1
_MARK_SAMPLES = 4
_MARK_WARMUP = 1


def _print_table(n: int, scenarios: dict[str, dict[str, float]]) -> None:
    print(f"\nPlugins catalog scale n={n}:", file=sys.stderr)
    print(
        f"  {'scenario':<20} {'n':>4} {'p50_ms':>8} {'p95_ms':>8} {'max_ms':>8}",
        file=sys.stderr,
    )
    for name, stats in scenarios.items():
        print(
            f"  {name:<20} {int(stats['n']):>4d} "
            f"{stats['p50_ms']:>8.2f} {stats['p95_ms']:>8.2f} "
            f"{stats['max_ms']:>8.2f}",
            file=sys.stderr,
        )


def _invoke_highlight_handler(pane: PluginsBrowserPane) -> None:
    """Run the queued ``OptionHighlighted`` work the j/k binding posts."""
    option_list = pane._option_list()
    if option_list is None or option_list.highlighted is None:
        return
    option = option_list.get_option_at_index(option_list.highlighted)
    pane.on_option_list_option_highlighted(
        OptionList.OptionHighlighted(option_list, option, option_list.highlighted)
    )


def _drive_j(pane: PluginsBrowserPane) -> None:
    """One j move plus the handler that actually does the per-key work."""
    option_list = pane._option_list()
    assert option_list is not None
    before = option_list.highlighted
    pane.action_next_option()
    if option_list.highlighted == before:
        pane.action_prev_option()
    _invoke_highlight_handler(pane)


def _matched_row_count(pane: PluginsBrowserPane) -> int:
    return sum(len(entries) for _, _, entries in pane._grouped)


def _time_ms(clock: Any, fn: Any) -> float:
    started = clock()
    fn()
    return (clock() - started) * 1000.0


async def _measure_pane_open(
    page: AcePage,
    *,
    clock: Any = time.perf_counter,
) -> tuple[PluginsBrowserPane, dict[str, float]]:
    samples: list[float] = []
    pane: PluginsBrowserPane | None = None
    for iteration in range(_PANE_OPEN_WARMUP + _PANE_OPEN_SAMPLES):
        started = clock()
        pane = await _open_plugins_pane(page)
        elapsed = (clock() - started) * 1000.0
        if iteration >= _PANE_OPEN_WARMUP:
            samples.append(elapsed)
        if iteration + 1 < _PANE_OPEN_WARMUP + _PANE_OPEN_SAMPLES:
            await page.press("escape")
            await page.expect_no_modal()
    assert pane is not None
    return pane, summarize_ms(samples)


def _measure_j_presses(pane: PluginsBrowserPane) -> dict[str, float]:
    samples = [
        _time_ms(time.perf_counter, lambda: _drive_j(pane)) for _ in range(_J_PRESSES)
    ]
    return summarize_ms(samples)


def _measure_jump_hint(pane: PluginsBrowserPane) -> dict[str, float]:
    samples: list[float] = []
    for iteration in range(_JUMP_WARMUP + _JUMP_SAMPLES):
        elapsed = _time_ms(time.perf_counter, pane.action_jump_to_entry)
        if pane.jump_mode_active:
            pane.exit_jump_mode()
        if iteration >= _JUMP_WARMUP:
            samples.append(elapsed)
    return summarize_ms(samples)


def _measure_install_mark(pane: PluginsBrowserPane) -> dict[str, float]:
    samples: list[float] = []
    for iteration in range(_MARK_WARMUP + _MARK_SAMPLES):
        elapsed = _time_ms(time.perf_counter, pane.action_toggle_install_mark)
        _invoke_highlight_handler(pane)
        if iteration >= _MARK_WARMUP:
            samples.append(elapsed)
    if pane._marked:
        pane._clear_marks()
    return summarize_ms(samples)


def _apply_filter(pane: PluginsBrowserPane, value: str) -> None:
    """Run the real ``on_input_changed`` path, then settle its debounce.

    ``on_input_changed`` only schedules the rebuild now, so the pending
    timer is cancelled and its callback invoked directly to measure the
    settled cost instead of waiting out the real debounce delay.
    """
    filter_input = pane.query_one("#updates-filter-input", Input)
    pane.on_input_changed(Input.Changed(filter_input, value))
    debouncer = pane._detail_debouncer
    if debouncer is not None:
        debouncer.cancel()
    pane._apply_filter()


def _measure_filter_keystroke(pane: PluginsBrowserPane) -> dict[str, float]:
    samples: list[float] = []
    for iteration in range(_FILTER_WARMUP + _FILTER_SAMPLES):
        _apply_filter(pane, "")
        elapsed = _time_ms(
            time.perf_counter, lambda: _apply_filter(pane, FILTER_KEYSTROKE)
        )
        if iteration >= _FILTER_WARMUP:
            samples.append(elapsed)
    return summarize_ms(samples)


async def _measure_size(
    page: AcePage,
    n: int,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    _patch_catalog(monkeypatch, catalog=make_scale_catalog(n), uv_tool=_uv_tool())
    pane, pane_open = await _measure_pane_open(page)
    assert pane._scope == "all"
    assert pane._catalog is not None
    assert len(pane._catalog.entries) == n
    j_press = _measure_j_presses(pane)
    jump_hint = _measure_jump_hint(pane)
    installable = next(
        row for row in pane._flat_rows() if "install" in row.capabilities
    )
    option_list = pane._option_list()
    assert option_list is not None
    option_list.highlighted = pane._row_option_index[installable.key]
    _invoke_highlight_handler(pane)
    install_mark = _measure_install_mark(pane)
    filter_keystroke = _measure_filter_keystroke(pane)
    match_count = _matched_row_count(pane)
    expected_matches = scale_filter_match_count(n)
    assert match_count == expected_matches, (
        f"filter match count at n={n}: {match_count} != {expected_matches}"
    )
    await page.press("escape")
    await page.expect_no_modal()
    return {
        "filter_matches": float(match_count),
        "pane_open": pane_open,
        "filter_keystroke": filter_keystroke,
        "j_press": j_press,
        "jump_hint": jump_hint,
        "install_mark": install_mark,
    }


@pytest.mark.parametrize("catalog_size", list(CATALOG_SCALE_SIZES))
async def test_bench_plugins_catalog_scale(
    catalog_size: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Record Plugins-pane interaction baselines at one catalog size."""
    _patch_other_panes(monkeypatch)
    async with AcePage() as page:
        scenarios = await _measure_size(page, catalog_size, monkeypatch)

    _print_table(
        catalog_size,
        {name: value for name, value in scenarios.items() if isinstance(value, dict)},
    )
    assert scenarios["pane_open"]["n"] == float(_PANE_OPEN_SAMPLES)
    assert scenarios["filter_keystroke"]["n"] == float(_FILTER_SAMPLES)
    assert scenarios["j_press"]["n"] == float(_J_PRESSES)
    assert scenarios["jump_hint"]["n"] == float(_JUMP_SAMPLES)
    assert scenarios["install_mark"]["n"] == float(_MARK_SAMPLES)
    assert scenarios["filter_matches"] == float(scale_filter_match_count(catalog_size))
    assert scenarios["filter_keystroke"]["p95_ms"] < TARGET_P95_MS
    assert scenarios["j_press"]["p95_ms"] < TARGET_P95_MS

    if os.environ.get("SASE_PLUGIN_CATALOG_SCALE_WRITE_BASELINE") == "1":
        merge_baseline_section(
            "tui",
            {str(catalog_size): scenarios},
        )
