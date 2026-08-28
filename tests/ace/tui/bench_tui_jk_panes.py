"""Patches and AXE j/k key-to-paint benchmark cases."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.app import AceApp
from tests.ace.tui._bench_tui_jk_helpers import (
    _AXE_P95_BUDGET_MS,
    _KEYS_PER_SCENARIO,
    _PATCHES_P95_BUDGET_MS,
    _install_axe_fixture,
    _make_patch,
    _perf_jsonl as _perf_jsonl,
    _print_table,
    _read_samples,
    _summarize,
    _wait_for_startup,
    _warm_axe_navigation,
)

pytestmark = pytest.mark.slow


async def test_bench_patches_jk(_perf_jsonl: Path, tmp_path: Path) -> None:
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
    """Measure cached j/k latency on the Axe tab with synthetic AXE rows."""
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("tab")  # next_tab: agents -> patches
        await pilot.pause()
        await pilot.press("tab")  # next_tab: patches -> axe
        await pilot.pause()
        _install_axe_fixture(app)
        await pilot.pause(0.2)
        assert len(app._axe_items) > (_KEYS_PER_SCENARIO * 2)
        await _warm_axe_navigation(pilot)
        before = len(_read_samples(_perf_jsonl))
        for _ in range(_KEYS_PER_SCENARIO):
            await pilot.press("j")
            await pilot.pause(0.01)
        for _ in range(_KEYS_PER_SCENARIO):
            await pilot.press("k")
            await pilot.pause(0.01)

    samples = _read_samples(_perf_jsonl)[before:]
    summary = _summarize(samples)
    _print_table("Axe tab cached j/k baseline:", summary)
    assert samples, "perf JSONL captured no AXE samples; instrumentation may be broken"
    assert {str(sample["tab"]) for sample in samples} == {"axe"}
    assert {"next", "prev"} <= set(summary)
    assert all(stats["p95"] < _AXE_P95_BUDGET_MS for stats in summary.values()), (
        f"AXE cached j/k exceeded {_AXE_P95_BUDGET_MS:g} ms p95: {summary}"
    )
    stall_path = _perf_jsonl.with_name("tui_stalls.jsonl")
    assert not stall_path.exists() or not stall_path.read_text().strip()
