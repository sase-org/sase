"""Agents-tab j/k key-to-paint with the ≡ RECORD deck pinned (the triage loop).

Epic sase-1jm.4.2 (``proof``) asks for the j/k bench with RECORD pinned:
Reply above, RECORD below, stepping through inbox agents at triage
cadence -- each key waits out the detail debounce so the lower panel
loads that agent before the next key. The lower panel alternates between
Main and RECORD in interleaved rounds inside one app, so the printed
delta is what RECORD adds to the loop. The off-thread loader, document
build and card host are real; agents carry artifacts dirs so the facts
extras do their usual disk reads off-thread. The bench also proves an
idle tick starts no Record worker: with RECORD painted and the selection
settled, a pause past the refresh interval must not call
``RecordDeckView.run_worker`` again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing.wait import wait_for
from sase.ace.tui.app import AceApp
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout
from sase.ace.tui.widgets.decks.record.view import RecordDeckView
from tests.ace.tui._bench_tui_jk_helpers import (
    _AGENTS_LARGE_LIST_P95_BUDGET_MS,
    _LINK_RAIL_AB_ROUNDS,
    _install_agents_fixture,
    _print_table,
    _read_samples,
    _summarize,
    _wait_for_startup,
    _warm_agents_navigation,
)

pytest_plugins = ("tests.ace.tui._bench_tui_jk_helpers",)
pytestmark = pytest.mark.slow

_TRIAGE_KEYS_PER_ROUND = 8
# Past the 0.15 s detail debounce plus the off-thread RECORD load and apply.
_TRIAGE_DWELL_S = 0.35
# Idle-tick settle: past the detail debounce, so a settled selection starts
# no further Record work.
_IDLE_SETTLE_S = 1.0


def _give_agents_record_content(app: AceApp, tmp_path: Path) -> None:
    """Give every fixture agent Reply content and an artifacts dir."""
    for agent in app._agents:
        directory = tmp_path / str(agent.agent_name)
        directory.mkdir(parents=True, exist_ok=True)
        response = directory / "response.md"
        response.write_text("reply line\n" * 20, encoding="utf-8")
        agent.artifacts_dir = str(directory)
        agent.response_path = str(response)


async def _collect_triage_jk(
    pilot: object, _perf_jsonl: Path
) -> list[dict[str, object]]:
    """Run one warmed j/k stretch at triage cadence; return its own samples."""
    await _warm_agents_navigation(pilot)
    await pilot.pause(_TRIAGE_DWELL_S)  # type: ignore[attr-defined]
    before = len(_read_samples(_perf_jsonl))
    for key in ("j", "k"):
        for _ in range(_TRIAGE_KEYS_PER_ROUND):
            await pilot.press(key)  # type: ignore[attr-defined]
            await pilot.pause(_TRIAGE_DWELL_S)  # type: ignore[attr-defined]
    return _read_samples(_perf_jsonl)[before:]


async def test_bench_agents_jk_with_record_pinned(
    _perf_jsonl: Path, tmp_path: Path
) -> None:
    """Time the triage loop: Reply above, RECORD below, j/k across agents."""
    import sase.ace.tui.widgets.decks.record.loader as loader_module

    loader_module.clear_record_cache()
    worker_calls = 0
    real_run_worker = RecordDeckView.run_worker

    def _counting_run_worker(
        self: RecordDeckView, *args: object, **kwargs: object
    ) -> object:
        nonlocal worker_calls
        worker_calls += 1
        return real_run_worker(self, *args, **kwargs)  # type: ignore[arg-type]

    RecordDeckView.run_worker = _counting_run_worker  # type: ignore[method-assign]
    try:
        app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
        async with app.run_test() as pilot:
            await _wait_for_startup(app, pilot)
            await pilot.press("ctrl+l")
            await pilot.pause()
            _install_agents_fixture(app)
            _give_agents_record_content(app, tmp_path)
            app._refresh_agents_display(list_changed=True, defer_detail=True)
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
            await pilot.pause()
            detail.set_deck_preferred_card(0, "reply")

            async def _arm(*, record: bool) -> list[dict[str, object]]:
                # Uncached every round: each subject pays the full off-thread
                # load and document apply, the worst case of a first triage pass.
                loader_module.clear_record_cache()
                detail.show_deck(1, DeckId.RECORD if record else DeckId.MAIN)
                await pilot.pause()
                return await _collect_triage_jk(pilot, _perf_jsonl)

            # Discarded rounds absorb one-time layout and renderer work.
            await _arm(record=False)
            await _arm(record=True)
            assert detail.deck_area.panel(1)._record_document is not None, (
                "RECORD never loaded a document for the bench subjects"
            )
            assert worker_calls > 1, "RECORD loaded no subject off-thread"

            main_samples: list[dict[str, object]] = []
            record_samples: list[dict[str, object]] = []
            for _ in range(_LINK_RAIL_AB_ROUNDS):
                main_samples += await _arm(record=False)
                loaded = worker_calls
                record_samples += await _arm(record=True)
                assert worker_calls > loaded, "RECORD loaded no subject this round"

            # Idle-tick proof: RECORD painted and the selection settled, so
            # pauses past the detail debounce must start no Record worker.
            # (The record package owns no timer: its only run_worker call
            # lives in show_subject, driven by selection and deck changes.)
            record_view = detail.deck_area.panel(1).record_view

            def _record_quiesced() -> bool:
                worker = record_view._current_worker
                return worker is None or not worker.is_running

            await wait_for(pilot, _record_quiesced, timeout=10.0)
            await pilot.pause(_IDLE_SETTLE_S)  # type: ignore[attr-defined]
            idle_baseline = worker_calls
            await pilot.pause(_IDLE_SETTLE_S)  # type: ignore[attr-defined]
            await pilot.pause(_IDLE_SETTLE_S)  # type: ignore[attr-defined]
            assert worker_calls == idle_baseline, (
                f"idle tick started {worker_calls - idle_baseline} Record worker(s)"
            )
    finally:
        RecordDeckView.run_worker = real_run_worker  # type: ignore[method-assign]

    main = _summarize(main_samples)
    record = _summarize(record_samples)
    _print_table("Agents tab j/k, Reply above Main (baseline):", main)
    _print_table("Agents tab j/k, Reply above RECORD (triage loop):", record)
    assert main and record, "perf JSONL captured no samples"
    for scenario, stats in record.items():
        baseline = main.get(scenario)
        delta = stats["p95"] - baseline["p95"] if baseline else float("nan")
        print(f"{scenario}: RECORD-pinned p95 delta {delta:+.2f} ms")
        assert stats["p95"] < _AGENTS_LARGE_LIST_P95_BUDGET_MS, (
            f"RECORD-pinned {scenario} p95 {stats['p95']:.2f} ms exceeded "
            f"{_AGENTS_LARGE_LIST_P95_BUDGET_MS:g} ms: {record}"
        )
