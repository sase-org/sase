"""Isolated Services j/k sample-window regressions (sase-1vy.3).

Covers the real ``test_bench_axe_jk`` selector without requiring host
contention or 40 rendered keypresses. The slow benchmark is imported under a
non-test alias so it is never collected twice.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from sase.ace.tui.tab_order import SERVICES_TAB
from tests.ace.tui import bench_tui_jk_panes as bench_panes_alias
from tests.ace.tui._bench_tui_jk_helpers import (
    _assert_durable_window_complete,
    _AXE_MEASURED_ACTIONS,
    _AXE_P95_BUDGET_MS,
    _drain_perf_writer,
    _select_axe_measured_samples,
    _summarize,
)

bench_axe_jk_impl = bench_panes_alias.test_bench_axe_jk


def _row(
    *,
    app_instance_id: str,
    tab: str,
    action: str,
    t_keypress: float,
    paint_ms: float,
) -> dict[str, object]:
    return {
        "app_instance_id": app_instance_id,
        "tab": tab,
        "action": action,
        "t_keypress": t_keypress,
        "paint_ms": paint_ms,
    }


def _timer_row(*, tab: str, action: str, t_keypress: float) -> dict[str, object]:
    return {"tab": tab, "action": action, "t_keypress": t_keypress}


def test_mixed_rows_only_measured_pair_enters_summary() -> None:
    """Foreign rows are excluded before summarization, regardless of order."""
    app_id = "bench-app-mixed"
    other_app = "bench-app-other"
    start, end = 100.0, 200.0
    measured_next = _row(
        app_instance_id=app_id,
        tab=SERVICES_TAB,
        action="next",
        t_keypress=140.0,
        paint_ms=5.0,
    )
    measured_prev = _row(
        app_instance_id=app_id,
        tab=SERVICES_TAB,
        action="prev",
        t_keypress=150.0,
        paint_ms=6.0,
    )
    # Write order is shuffled on purpose: post-window first, measured last.
    rows = [
        _row(
            app_instance_id=app_id,
            tab=SERVICES_TAB,
            action="next",
            t_keypress=210.0,
            paint_ms=800.0,
        ),
        measured_prev,
        _row(
            app_instance_id=other_app,
            tab=SERVICES_TAB,
            action="next",
            t_keypress=130.0,
            paint_ms=700.0,
        ),
        _row(
            app_instance_id=app_id,
            tab="artifacts",
            action="prev",
            t_keypress=120.0,
            paint_ms=600.0,
        ),
        _row(
            app_instance_id=app_id,
            tab="agents",
            action="next",
            t_keypress=110.0,
            paint_ms=500.0,
        ),
        measured_next,
        _row(
            app_instance_id=app_id,
            tab=SERVICES_TAB,
            action="next",
            t_keypress=90.0,
            paint_ms=5.0,
        ),
    ]
    selected = _select_axe_measured_samples(
        rows, app_instance_id=app_id, start=start, end=end
    )
    assert (
        selected == [measured_prev, measured_next]
        or selected
        == [
            measured_next,
            measured_prev,
        ]
        or sorted(
            [float(s["t_keypress"]) for s in selected]  # type: ignore[arg-type]
        )
        == [140.0, 150.0]
    )
    assert len(selected) == 2
    summary = _summarize(selected)
    assert set(summary) == {"next", "prev"}
    assert summary["next"]["p95"] == 5.0
    assert summary["prev"]["p95"] == 6.0
    # The old disk-count slice keeps every row after its boundary, so it
    # would retain the extreme foreign paints and fail the tab assertion.
    old_slice = rows[1:]
    assert {str(s["tab"]) for s in old_slice} != {SERVICES_TAB}
    assert max(float(s["paint_ms"]) for s in old_slice) >= 500.0  # type: ignore[arg-type]


async def test_delayed_publication_waits_for_fifo_boundary() -> None:
    """Late writes land before the read; old and foreign rows stay out."""
    import threading

    from sase.ace.tui.util.perf_writer import PerfWriter

    app_id = "bench-app-delayed"
    start, end = 100.0, 200.0
    published: list[dict[str, object]] = []
    lock = threading.Lock()

    def _append(row: dict[str, Any]) -> None:
        with lock:
            published.append(dict(row))

    writer = PerfWriter()
    gate = threading.Event()
    gate.set()

    def _gated_append(row: dict[str, Any]) -> None:
        assert gate.wait(timeout=5.0)
        _append(row)

    old_row = _row(
        app_instance_id=app_id,
        tab=SERVICES_TAB,
        action="next",
        t_keypress=90.0,
        paint_ms=5.0,
    )
    foreign_row = _row(
        app_instance_id="bench-app-foreign",
        tab=SERVICES_TAB,
        action="next",
        t_keypress=150.0,
        paint_ms=900.0,
    )
    late_row = _row(
        app_instance_id=app_id,
        tab=SERVICES_TAB,
        action="prev",
        t_keypress=160.0,
        paint_ms=7.0,
    )
    assert writer.submit(_gated_append, old_row)
    assert writer.submit(_gated_append, foreign_row)
    assert writer.submit(_gated_append, late_row)
    await _drain_perf_writer(timeout=5.0, writer=writer)
    with lock:
        snapshot = list(published)
    selected = _select_axe_measured_samples(
        snapshot, app_instance_id=app_id, start=start, end=end
    )
    assert len(selected) == 1
    assert float(selected[0]["t_keypress"]) == 160.0  # type: ignore[arg-type]


def test_invalid_capture_fails_clearly() -> None:
    """Wrong tab, empty window, missing direction, and lost rows all fail."""
    app_id = "bench-app-invalid"
    start, end = 100.0, 200.0
    # Wrong active tab: every row is Agents, so the Services selector is empty.
    agents_rows = [
        _row(
            app_instance_id=app_id,
            tab="agents",
            action="next",
            t_keypress=140.0,
            paint_ms=5.0,
        )
    ]
    assert (
        _select_axe_measured_samples(
            agents_rows, app_instance_id=app_id, start=start, end=end
        )
        == []
    )
    # No matching samples at all.
    assert (
        _select_axe_measured_samples([], app_instance_id=app_id, start=start, end=end)
        == []
    )
    # Empty selector input must fail the window check, never pass vacuously.
    with pytest.raises(AssertionError, match="no durable"):
        _assert_durable_window_complete(
            [_timer_row(tab=SERVICES_TAB, action="next", t_keypress=140.0)],
            [],
            start,
            end,
        )
    # Missing direction: only next is present, so the benchmark's
    # {"next", "prev"} coverage assertion would fail.
    only_next = [
        _row(
            app_instance_id=app_id,
            tab=SERVICES_TAB,
            action="next",
            t_keypress=140.0,
            paint_ms=5.0,
        )
    ]
    selected = _select_axe_measured_samples(
        only_next, app_instance_id=app_id, start=start, end=end
    )
    assert _summarize(selected).keys() == {"next"}
    assert "prev" not in _summarize(selected)
    # Missing durable row: the timer saw two keypresses, disk kept one.
    timer_samples = [
        _timer_row(tab=SERVICES_TAB, action="next", t_keypress=140.0),
        _timer_row(tab=SERVICES_TAB, action="prev", t_keypress=150.0),
    ]
    with pytest.raises(AssertionError, match="lost 1 measured"):
        _assert_durable_window_complete(timer_samples, only_next, start, end)
    # Duplicate durable row.
    duplicated = only_next + only_next
    with pytest.raises(AssertionError, match="duplicate"):
        _assert_durable_window_complete(
            [_timer_row(tab=SERVICES_TAB, action="next", t_keypress=140.0)],
            duplicated,
            start,
            end,
        )
    # Empty app instance id never matches.
    with pytest.raises(AssertionError, match="nonempty app_instance_id"):
        _select_axe_measured_samples(
            only_next, app_instance_id="", start=start, end=end
        )


async def test_drain_helper_reports_admission_and_timeout() -> None:
    """Queue-full and stuck writers fail fast without a long wait."""

    class _FullWriter:
        def submit(self, _sink: object, _row: object) -> bool:
            return False

    with pytest.raises(AssertionError, match="queue full"):
        await _drain_perf_writer(timeout=0.2, writer=_FullWriter())

    class _StuckWriter:
        def submit(self, _sink: object, _row: object) -> bool:
            return True

    with pytest.raises(AssertionError, match="did not drain"):
        await _drain_perf_writer(timeout=0.05, writer=_StuckWriter())


def test_latency_integrity_real_regression_still_fails() -> None:
    """A slow matching Services row keeps failing the unchanged budget."""
    assert _AXE_P95_BUDGET_MS == 16.0
    app_id = "bench-app-latency"
    start, end = 100.0, 200.0
    slow_rows = [
        _row(
            app_instance_id=app_id,
            tab=SERVICES_TAB,
            action="next",
            t_keypress=140.0,
            paint_ms=25.0,
        ),
        _row(
            app_instance_id=app_id,
            tab=SERVICES_TAB,
            action="prev",
            t_keypress=150.0,
            paint_ms=26.0,
        ),
    ]
    selected = _select_axe_measured_samples(
        slow_rows, app_instance_id=app_id, start=start, end=end
    )
    assert len(selected) == 2
    summary = _summarize(selected)
    assert summary["next"]["p95"] == 25.0
    assert summary["prev"]["p95"] == 26.0
    assert any(stats["p95"] >= _AXE_P95_BUDGET_MS for stats in summary.values()), (
        "over-budget Services rows must still fail the p95 gate"
    )


def test_bench_collection_path_uses_window_selector() -> None:
    """The slow benchmark must use the window selector, not a row-count slice."""
    assert bench_axe_jk_impl is bench_panes_alias.test_bench_axe_jk
    source = inspect.getsource(bench_axe_jk_impl)
    assert "initial_tab=SERVICES_TAB" in source
    assert "_select_axe_measured_samples" in source
    assert "_drain_perf_writer" in source
    assert "_assert_durable_window_complete" in source
    assert "before = len(_read_samples" not in source
    assert '== {"axe"}' not in source
    assert SERVICES_TAB == "services"
    assert _AXE_MEASURED_ACTIONS == frozenset({"next", "prev"})
