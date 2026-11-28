"""Patches and AXE j/k key-to-paint benchmark cases."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.app import AceApp
from sase.ace.tui.tab_order import SERVICES_TAB
from tests.ace.tui._bench_tui_jk_helpers import (
    _assert_durable_window_complete,
    _assert_no_stall_rows,
    _AXE_P95_BUDGET_MS,
    _capture_measurement_window,
    _drain_perf_writer,
    _KEYS_PER_SCENARIO,
    _PATCHES_P95_BUDGET_MS,
    _install_axe_fixture,
    _make_patch,
    _print_table,
    _read_samples,
    _select_axe_measured_samples,
    _summarize,
    _wait_for_startup,
    _warm_axe_navigation,
)

pytest_plugins = ("tests.ace.tui._bench_tui_jk_helpers",)
pytestmark = pytest.mark.slow


async def test_bench_patches_jk(
    _perf_jsonl: Path,
    tmp_path: Path,
) -> None:
    """Measure j/k latency on the Patches tab with 50 synthetic Patches."""
    gp_file = tmp_path / "bench" / "bench.sase"
    gp_file.parent.mkdir(parents=True)
    gp_file.write_text("")
    cs_list = [_make_patch(f"cs_{i:03d}", gp_file) for i in range(50)]

    with patch(
        "sase.ace.patch.find_all_patches_cached",
        return_value=cs_list,
    ):
        app = AceApp(
            query='"cs_"',
            auto_start_axe=False,
            initial_tab="patches",
        )
        async with app.run_test() as pilot:
            await _wait_for_startup(app, pilot)
            for _ in range(_KEYS_PER_SCENARIO):
                await pilot.press("j")
                await pilot.pause(0.01)
            for _ in range(_KEYS_PER_SCENARIO):
                await pilot.press("k")
                await pilot.pause(0.01)

    samples = _read_samples(_perf_jsonl)
    summary = _summarize(samples)
    _print_table("Patches tab j/k baseline:", summary)
    assert samples, "perf JSONL captured no samples; instrumentation may be broken"
    assert all(stats["p95"] < _PATCHES_P95_BUDGET_MS for stats in summary.values()), (
        f"Patches j/k exceeded {_PATCHES_P95_BUDGET_MS:g} ms p95: {summary}"
    )


async def test_bench_axe_jk(_perf_jsonl: Path) -> None:
    """Measure cached j/k latency on Services (Axe) with synthetic AXE rows."""
    app = AceApp(
        query="!!!",
        auto_start_axe=False,
        refresh_interval=0,
        initial_tab=SERVICES_TAB,
    )
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        assert app.current_tab == SERVICES_TAB, (
            f"benchmark must start on Services, found {app.current_tab!r}"
        )
        _install_axe_fixture(app)
        await pilot.pause(0.2)
        assert len(app._axe_items) > (_KEYS_PER_SCENARIO * 2)
        await _warm_axe_navigation(pilot)
        assert app.current_tab == SERVICES_TAB, (
            f"benchmark must stay on Services after warmup, found {app.current_tab!r}"
        )
        timer = app._jk_perf
        assert timer is not None, "perf timer missing; SASE_TUI_PERF=1 is required"
        app_instance_id = timer.app_instance_id or getattr(
            app, "_app_instance_id", None
        )
        assert app_instance_id, "benchmark app is missing its app_instance_id"
        start = _capture_measurement_window()
        for _ in range(_KEYS_PER_SCENARIO):
            await pilot.press("j")
            await pilot.pause(0.01)
        for _ in range(_KEYS_PER_SCENARIO):
            await pilot.press("k")
            await pilot.pause(0.01)
        end = _capture_measurement_window()
        assert app.current_tab == SERVICES_TAB, (
            f"benchmark must stay on Services through measured input, found {app.current_tab!r}"
        )
        await _drain_perf_writer()
        timer_samples = list(timer.samples())

    all_rows = _read_samples(_perf_jsonl)
    samples = _select_axe_measured_samples(
        all_rows,
        app_instance_id=str(app_instance_id),
        start=start,
        end=end,
    )
    summary = _summarize(samples)
    _print_table("Services (Axe) tab cached j/k baseline:", summary)
    assert samples, (
        "perf JSONL captured no Services samples; instrumentation may be broken"
    )
    assert {str(sample["tab"]) for sample in samples} == {SERVICES_TAB}
    assert {"next", "prev"} <= set(summary)
    _assert_durable_window_complete(timer_samples, samples, start, end)
    assert all(stats["p95"] < _AXE_P95_BUDGET_MS for stats in summary.values()), (
        f"Services (Axe) cached j/k exceeded {_AXE_P95_BUDGET_MS:g} ms p95: {summary}"
    )
    stall_path = _perf_jsonl.with_name("tui_stalls.jsonl")
    _assert_no_stall_rows(stall_path)
