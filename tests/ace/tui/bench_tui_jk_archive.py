"""Archive-tab warm-open and j/k key-to-paint benchmarks (child epic sase-1jm.3.1).

Run explicitly with::

    pytest -s -m slow tests/ace/tui/bench_tui_jk_archive.py

The corpus is real and archive-scale: 11,000 same-day rows compiled through
the Rust-backed facade from a synthetic tmp index (plus a small tail of
older days for banner variety), with no dependency on the current user's
dismissed bundles. The cold corpus/facet build cost is owned by
``tests/perf/bench_agent_archive_corpus.py``; this module measures the TUI
side only: warm ``,a`` to first rows and steady-state j/k key-to-paint on
the real mounted Archive column, so UI scheduling and paint are in the
number, not just facade query time.

A warm reopen serves the held windows synchronously and revalidates
off-thread afterwards. The budgeted warm-open number is open-to-first-rows;
an untimed SVG export then proves those rows actually painted, and the
bench proves the revalidation settles with rows still current. j/k uses the
same ``SASE_TUI_PERF=1`` event-level harness as the Inbox benches: the
Archive key route finalizes the in-flight paint sample on the next frame,
so the p95 below is key-to-paint, not Pilot round-trip time.
"""

from __future__ import annotations

import statistics
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._archive_controller import (
    archive_corpus_is_warm,
    archive_corpus_snapshot,
    note_inbox_applied_for_archive,
)
from sase.ace.tui.actions.agents._archive_view import (
    close_agents_archive_view,
    open_agents_archive_view,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_archive_controller import ArchiveRevalidationTokens
from sase.ace.tui.widgets.agents_archive import ArchiveList
from sase.core.agent_archive_facade import (
    agents_archive_profile,
    compile_agent_archive_corpus,
)
from sase.feature_flags import override_flags
from tests._agent_archive_index_fixtures import insert_archive_rows
from tests.ace.tui._agent_archive_column_helpers import complete_load
from tests.ace.tui._bench_tui_jk_helpers import (
    _perf_jsonl as _perf_jsonl,
    _print_table,
    _read_samples,
    _summarize,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
)

pytest_plugins = ("tests.ace.tui._bench_tui_jk_helpers",)
pytestmark = pytest.mark.slow

_TODAY_ROWS = 11_000
_OLDER_ROWS = 200
_WARM_OPEN_BUDGET_MS = 100.0
_ARCHIVE_JK_P95_BUDGET_MS = 16.0
_KEYS_PER_DIRECTION = 25
_WARM_REOPENS = 7


def _inbox_agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="live-agent",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="crs",
        raw_suffix="20260527120000",
        agent_name="live.agent",
    )


def _scale_index_rows() -> list[dict[str, Any]]:
    """11k same-day index rows plus yesterday/older tails."""
    now = datetime.now(UTC)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    older = (now - timedelta(days=40)).strftime("%Y-%m-%d")
    rows = [
        {
            "run_id": f"s{i:05d}",
            "name": f"scale.{i:05d}",
            "stop_time": f"{today}T{i % 24:02d}:00:00Z",
            "status": "DONE",
        }
        for i in range(_TODAY_ROWS)
    ]
    rows += [
        {
            "run_id": f"y{i:03d}",
            "name": f"yday.{i:03d}",
            "stop_time": f"{yesterday}T{i % 24:02d}:00:00Z",
            "status": "DONE",
        }
        for i in range(_OLDER_ROWS)
    ]
    rows += [
        {
            "run_id": f"o{i:03d}",
            "name": f"old.{i:03d}",
            "stop_time": f"{older}T12:00:00Z",
            "status": "DONE",
        }
        for i in range(_OLDER_ROWS)
    ]
    return rows


def _wire_real_corpus(app: Any, corpus: Any, profile: Any) -> None:
    app._archive_get_corpus = lambda **kwargs: SimpleNamespace(
        corpus=corpus, profile=profile
    )
    app._archive_probe_tokens = lambda: ArchiveRevalidationTokens(
        index_exists=True,
        index_stat=(1, 2),
        link_signature=(("proj", 1, 2),),
        profile_digest=str(getattr(profile, "digest", "") or ""),
        rebuilding=False,
        indexed_rows=0,
    )
    app._archive_load_facets = lambda: {}
    app._archive_profile = profile


def _run_row_keys(page: AcePage) -> tuple[str, ...]:
    keys = (
        page.app.query_one("#archive-list", ArchiveList).item_keys
        if page.app.query("#archive-list")
        else ()
    )
    return tuple(keys)


async def _open_to_first_rows_ms(app: Any, page: AcePage) -> tuple[float, float]:
    """Time one open until run rows land in the list widget.

    Returns ``(sync_open_ms, rows_ms)``. The timer starts before ``open()``
    so the synchronous chrome work counts; a tight poll loop (no app-wide
    pilot settle) keeps harness quiescence out of the budgeted number.
    Paint is proved separately, untimed, by polling SVG exports: once rows
    are in the widget, Textual paints them on the next frame, so
    user-perceived first paint is rows-visible plus one frame quantum.
    (Pilot offers no bounded-frame wait: even ``pause(0.03)`` settles the
    whole app and costs ~130 ms here, which would measure quiescence,
    not Archive paint.)
    """
    import asyncio

    start = time.perf_counter()
    open_agents_archive_view(app)
    sync_open_ms = (time.perf_counter() - start) * 1000.0
    while not any("@" in key for key in _run_row_keys(page)):
        if time.perf_counter() - start > 30.0:
            raise AssertionError("timed out waiting for Archive rows after open")
        await asyncio.sleep(0.005)  # sase-test-wait: poll Archive rows
    return sync_open_ms, (time.perf_counter() - start) * 1000.0


async def _prove_rows_painted(
    page: AcePage, needle: str, timeout: float = 10.0
) -> None:
    """Poll SVG exports until Archive row text reaches pixels.

    ``page.screen`` stays blank in headless Pilot runs, but the SVG export
    renders the live DOM, so it is the honest paint oracle here.
    """
    import asyncio

    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        if needle in page.export_svg(title="archive paint proof"):
            return
        await asyncio.sleep(0.1)  # sase-test-wait: poll SVG paint proof
    raise AssertionError(f"Archive rows never painted {needle!r} on screen")


async def _settle_revalidation(page: AcePage, timeout: float = 30.0) -> None:
    """Wait until the post-open off-thread revalidation has applied."""
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        await page.pause()
        snapshot = archive_corpus_snapshot(page.app)
        if (
            snapshot.summary is not None
            and snapshot.status != "loading"
            and not snapshot.refreshing
        ):
            return
    raise AssertionError("archive revalidation did not settle after open")


async def test_bench_archive_warm_open_to_first_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Warm ``,a`` reopen shows first Archive rows within 100 ms (median)."""
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    insert_archive_rows(tmp_path, _scale_index_rows())
    profile = agents_archive_profile()
    corpus = compile_agent_archive_corpus(
        root=tmp_path,
        index_status={"status": "ok"},
        timezone="UTC",
        link_facets={},
    )
    with override_flags(agents_archive_view=True):
        async with AcePage(initial_tab="agents") as page:
            await wait_for_startup(page)
            app = page.app
            _wire_real_corpus(app, corpus, profile)
            note_inbox_applied_for_archive(app, load_state=complete_load())

            # Cold open: no warm handle yet. Reported, not budgeted: the
            # corpus/facet build cost belongs to bench_agent_archive_corpus.
            _cold_sync_ms, cold_ms = await _open_to_first_rows_ms(app, page)
            first_keys = _run_row_keys(page)
            assert len(first_keys) > 100, "the Today banner must page its 11k roots"
            await _settle_revalidation(page)
            assert archive_corpus_is_warm(app)

            warm_sync: list[float] = []
            warm_ms: list[float] = []
            for _ in range(_WARM_REOPENS):
                close_agents_archive_view(app)
                await page.pause()
                sync_ms, rows_ms = await _open_to_first_rows_ms(app, page)
                warm_sync.append(sync_ms)
                warm_ms.append(rows_ms)

            # The budgeted number is first rows from held windows. Paint is
            # proved untimed by screen text, and the revalidation must
            # settle with rows still current.
            await _prove_rows_painted(page, "scale.")
            await _settle_revalidation(page)
            assert archive_corpus_is_warm(app)
            assert len(_run_row_keys(page)) > 100

            median_warm = statistics.median(warm_ms)
            median_sync = statistics.median(warm_sync)
            print(
                f"\narchive warm-open ms: cold(first)={cold_ms:.1f} "
                f"warm median={median_warm:.1f} warm samples="
                f"{[f'{v:.1f}' for v in warm_ms]} "
                f"sync-open median={median_sync:.1f} "
                f"(budget {_WARM_OPEN_BUDGET_MS:g} ms)"
            )
            assert median_warm < _WARM_OPEN_BUDGET_MS, (
                f"warm Archive open median {median_warm:.1f} ms exceeds "
                f"{_WARM_OPEN_BUDGET_MS:g} ms"
            )


async def test_bench_archive_jk_at_scale(
    _perf_jsonl: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Archive j/k key-to-paint stays under 16 ms p95 at 11k-root scale."""
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    insert_archive_rows(tmp_path, _scale_index_rows())
    profile = agents_archive_profile()
    corpus = compile_agent_archive_corpus(
        root=tmp_path,
        index_status={"status": "ok"},
        timezone="UTC",
        link_facets={},
    )
    with override_flags(agents_archive_view=True):
        async with AcePage(initial_tab="agents", size=(80, 24)) as page:
            await wait_for_startup(page)
            app = page.app
            _wire_real_corpus(app, corpus, profile)
            note_inbox_applied_for_archive(app, load_state=complete_load())
            await _open_to_first_rows_ms(app, page)
            await _settle_revalidation(page)

            # Settle onto the first run row so j/k walks rows, not banners.
            await page.press("j")
            await page.pause(0.01)

            for key in ("j", "k"):
                for _ in range(_KEYS_PER_DIRECTION):
                    await page.press(key)
                    await page.pause(0.01)

    samples = [s for s in _read_samples(_perf_jsonl) if s.get("tab") == "agents"]
    summary = _summarize(samples)
    _print_table("Archive j/k key-to-paint at 11k roots (event-level):", summary)
    assert samples, "the Archive route must emit key-to-paint samples"
    assert all(
        stats["p95"] < _ARCHIVE_JK_P95_BUDGET_MS for stats in summary.values()
    ), f"Archive j/k exceeded {_ARCHIVE_JK_P95_BUDGET_MS:g} ms p95: {summary}"
