"""Deck-view ``P`` transition benchmarks (epic sase-1b1, phase verify).

Measures key-to-paint for every ordered view transition on the standard
5,000-line Reply (10 turns x 500 lines, reused from
``bench_tui_jk_blocks.py``), on a new 14,000-line pathological Reply, and
for a forced Files spread of 20 files x 2,000 lines.

Budgets (plan D10):

- standard Reply: p50 <= 150 ms and p95 <= 300 ms per transition.
- pathological Reply: max < 1,000 ms with no stall-watchdog row.
- forced Files spread: the keypress never blocks the event loop (the
  complete probe runs off-thread) and the deck paints within 1,000 ms of
  probe completion.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.app import AceApp
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId, DeckView
from tests.ace.tui._bench_tui_jk_helpers import (
    _KEYS_PER_SCENARIO,
    _print_table,
    _read_samples,
    _summarize,
    _wait_for_startup,
)

pytest_plugins = ("tests.ace.tui._bench_tui_jk_helpers",)
pytestmark = pytest.mark.slow

_TURNS = 10
_STANDARD_LINES_PER_TURN = 500
_PATHOLOGICAL_LINES_PER_TURN = 1400
_FILES_COUNT = 20
_FILES_LINES_PER_FILE = 2000

# D10 budgets, in milliseconds.
_STANDARD_P50_BUDGET_MS = 150.0
_STANDARD_P95_BUDGET_MS = 300.0
_PATHOLOGICAL_MAX_BUDGET_MS = 1000.0
_FILES_PAINT_AFTER_PROBE_BUDGET_MS = 1000.0

_STARTED = datetime(2026, 7, 18, 12, 0, 0)

_TRANSITIONS: tuple[tuple[DeckView, DeckView], ...] = (
    (DeckView.SPREAD, DeckView.PAGE_CARDS),
    (DeckView.SPREAD, DeckView.PAGE_BLOCKS),
    (DeckView.PAGE_CARDS, DeckView.SPREAD),
    (DeckView.PAGE_CARDS, DeckView.PAGE_BLOCKS),
    (DeckView.PAGE_BLOCKS, DeckView.SPREAD),
    (DeckView.PAGE_BLOCKS, DeckView.PAGE_CARDS),
)


def _write_reply_lines(directory: Path, label: str, lines: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "response.md").write_text(
        "\n".join(f"{label} reply line {index}" for index in range(lines)) + "\n",
        encoding="utf-8",
    )


def _make_view_session(
    tmp_path: Path, index: int, *, turns: int, lines_per_turn: int, tag: str
) -> Agent:
    members: list[Agent] = []
    for turn in range(turns):
        role = "plan" if turn == 0 else "code"
        suffix = "--plan" if turn == 0 else f"--code-{turn}"
        directory = tmp_path / f"bench-view-{tag}-s{index}-{suffix.strip('-')}"
        _write_reply_lines(directory, f"s{index}{suffix}", lines_per_turn)
        members.append(
            Agent(
                agent_type=AgentType.RUNNING,
                cl_name="bench-views",
                project_file="/tmp/bench-views.sase",
                status="DONE",
                start_time=_STARTED,
                raw_suffix=f"2026071812{index:02d}{turn:02d}",
                artifacts_dir=str(directory),
                response_path=str(directory / "response.md"),
                agent_name=f"benchview{index}{suffix}",
                agent_session=f"benchview{index}",
                agent_session_role=role,
                role_suffix=suffix,
                model="claude/opus",
                **({"plan_chain_root": True} if turn == 0 else {}),
            )
        )
    root = members[0]
    root.followup_agents = members[1:]
    for member in members[1:]:
        member.agent_session_container = root
    assert root.is_agent_session_container_row is True
    return root


def _install_view_sessions(
    app: AceApp, tmp_path: Path, *, turns: int, lines_per_turn: int, tag: str
) -> None:
    session = _make_view_session(
        tmp_path, 0, turns=turns, lines_per_turn=lines_per_turn, tag=tag
    )
    app._agents = [session]
    app._agents_with_children = [session]
    app._fold_counts = {}
    app._group_fold_registry = AgentGroupFoldRegistry()
    app._panel_group = AgentPanelGroup.from_agents([session])
    app._agent_panels_grouped = False
    app._current_group_key = None
    app.current_idx = 0
    app._invalidate_agent_panel_cache()


def _action_name(start: DeckView, target: DeckView) -> str:
    return f"view_{start.value}_to_{target.value}"


async def _measure_transitions(
    tmp_path: Path,
    log_path: Path,
    *,
    turns: int,
    lines_per_turn: int,
    tag: str,
) -> dict[str, dict[str, float]]:
    """Time every ordered view transition; return the per-action summary."""
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()
        _install_view_sessions(
            app, tmp_path, turns=turns, lines_per_turn=lines_per_turn, tag=tag
        )
        app._refresh_agents_display(list_changed=True, defer_detail=True)
        await pilot.pause()
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.set_deck_preferred_card(0, "reply")
        detail.set_deck_preferred_card(1, "reply")
        app._refresh_agents_display(list_changed=True, defer_detail=True)
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        await wait_for(
            pilot,
            lambda: any(
                bool(card.has_block_navigation) for card in panel._main_document.cards
            ),
        )
        panel.show_main_document(panel._main_document, "reply")
        await pilot.pause()
        assert any(
            bool(card.has_block_navigation) for card in panel._main_document.cards
        ), "bench session has no navigable Reply blocks"

        async def _settle(view: DeckView) -> None:
            panel.set_view_policy(DeckId.MAIN, view)
            await wait_for(pilot, lambda: panel.effective_layout(DeckId.MAIN) is view)
            # Wait until this generation's deferred body has been applied or
            # dropped, so one sample's UI-thread apply cannot fall inside
            # the next sample's paint window. The paint mark stays on the
            # first refresh after the key (the badge frame).
            await wait_for(
                pilot,
                lambda: (
                    int(getattr(panel, "_main_view_applied_generation", 0))
                    >= int(getattr(panel, "_view_generation", 0))
                ),
            )
            try:
                settled_view = panel.main_view
                await wait_for(
                    pilot,
                    lambda: (
                        int(getattr(settled_view, "_section_anchor_generation", -1))
                        == int(getattr(settled_view, "_section_generation", 0))
                    ),
                )
            except Exception:
                pass
            await pilot.pause()
            await pilot.pause()

        # Warm up the recomposition path in every direction.
        for start, target in _TRANSITIONS:
            await _settle(start)
            await _settle(target)

        for start, target in _TRANSITIONS:
            await _settle(start)
            for _ in range(_KEYS_PER_SCENARIO):
                action = _action_name(start, target)
                app._jk_perf_begin(action)
                panel.set_view_policy(DeckId.MAIN, target)
                jk_perf = app._jk_perf
                if jk_perf is not None:
                    app.call_after_refresh(jk_perf.mark_painted)
                await wait_for(
                    pilot,
                    lambda _t=target: panel.effective_layout(DeckId.MAIN) is _t,
                )
                await pilot.pause(0.02)
                await _settle(start)
    samples = [
        s for s in _read_samples(log_path) if str(s.get("action")).startswith("view_")
    ]
    summary = _summarize(samples)
    _print_table(f"Deck-view P transitions ({tag}):", summary)
    return summary


def _stall_rows(stall_path: Path) -> list[dict[str, Any]]:
    if not stall_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in stall_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            import json

            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


async def test_bench_deck_view_standard_reply(
    tmp_path: Path, _perf_jsonl: Path
) -> None:
    """Time every P transition on the 5,000-line Reply against D10."""
    summary = await _measure_transitions(
        tmp_path,
        _perf_jsonl,
        turns=_TURNS,
        lines_per_turn=_STANDARD_LINES_PER_TURN,
        tag="standard-5k",
    )
    assert len(summary) == len(_TRANSITIONS), f"missing transitions: {summary}"
    for action, stats in summary.items():
        assert stats["p50"] < _STANDARD_P50_BUDGET_MS, f"{action}: {stats}"
        assert stats["p95"] < _STANDARD_P95_BUDGET_MS, f"{action}: {stats}"


async def test_bench_deck_view_pathological_reply(
    tmp_path: Path,
    _perf_jsonl: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Time every P transition on a 14,000-line Reply: max < 1s, no stalls."""
    stall_path = _perf_jsonl.with_name("tui_stalls.jsonl")
    monkeypatch.setenv("SASE_TUI_STALL_THRESHOLD_SECONDS", "1.0")
    monkeypatch.setenv("SASE_TUI_PUMP_STALL_THRESHOLD_SECONDS", "1.0")
    monkeypatch.setenv("SASE_TUI_STALL_POLL_INTERVAL", "0.02")
    monkeypatch.setenv("SASE_TUI_PUMP_STALL_POLL_INTERVAL", "0.02")
    before = len(_stall_rows(stall_path))
    summary = await _measure_transitions(
        tmp_path,
        _perf_jsonl,
        turns=_TURNS,
        lines_per_turn=_PATHOLOGICAL_LINES_PER_TURN,
        tag="pathological-14k",
    )
    assert len(summary) == len(_TRANSITIONS), f"missing transitions: {summary}"
    for action, stats in summary.items():
        assert stats["max"] < _PATHOLOGICAL_MAX_BUDGET_MS, f"{action}: {stats}"
    assert len(_stall_rows(stall_path)) == before, "stall watchdog fired"


async def test_bench_deck_view_files_forced_spread(
    tmp_path: Path, _perf_jsonl: Path
) -> None:
    """Forced Files spread never blocks on keypress; paints < 1s after probe."""
    paths = [tmp_path / f"bench_file_{index:02d}.py" for index in range(_FILES_COUNT)]
    for index, path in enumerate(paths):
        path.write_text(
            "".join(
                f"file-{index:02d} line {line}\n"
                for line in range(_FILES_LINES_PER_FILE)
            ),
            encoding="utf-8",
        )
    from tests.ace.tui.widgets._agent_display_helpers import make_agent

    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()
        agent = make_agent(
            agent_name="benchfiles",
            status="DONE",
            extra_files=[str(path) for path in paths],
        )
        app._agents = [agent]
        app._agents_with_children = [agent]
        app._fold_counts = {}
        app._group_fold_registry = AgentGroupFoldRegistry()
        app._panel_group = AgentPanelGroup.from_agents([agent])
        app._agent_panels_grouped = False
        app._current_group_key = None
        app.current_idx = 0
        app._invalidate_agent_panel_cache()
        app._refresh_agents_display(list_changed=True, defer_detail=True)
        await pilot.pause()
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(agent)
        await pilot.pause()
        detail.show_deck(0, DeckId.FILES)
        panel = detail.deck_area.panel(0)
        await wait_for(pilot, lambda: panel._files_probe_slots != ())

        probe_done: list[float] = []
        painted: list[float] = []
        real_result = panel._on_files_probe_result

        def _timed_result(
            probe: Any, result_agent: Any, slots: tuple[str, ...], subject: Any
        ) -> None:
            probe_done.append(time.perf_counter())
            real_result(probe, result_agent, slots, subject)
            app.call_after_refresh(lambda: painted.append(time.perf_counter()))

        panel._on_files_probe_result = _timed_result  # type: ignore[method-assign]

        pressed = time.perf_counter()
        panel.set_view_policy(DeckId.FILES, DeckView.SPREAD)
        keypress_ms = (time.perf_counter() - pressed) * 1000.0
        # The keypress returns while the deck is still paged: the complete
        # probe runs off-thread and never blocks the event loop.
        assert panel._files_spread_pending is True
        assert panel.effective_layout(DeckId.FILES) is DeckView.PAGE_CARDS
        await wait_for(pilot, lambda: panel.is_spread(DeckId.FILES), timeout=30.0)
        await pilot.pause()
        await pilot.pause()
        assert probe_done, "probe result was never applied"
        assert painted, "paint after probe was never observed"
        after_probe_ms = (painted[-1] - probe_done[-1]) * 1000.0
        print(
            f"\nFiles forced spread (20x2000): keypress_ms={keypress_ms:.2f} "
            f"after_probe_ms={after_probe_ms:.2f}",
        )
        assert after_probe_ms < _FILES_PAINT_AFTER_PROBE_BUDGET_MS, (
            f"keypress_ms={keypress_ms:.2f} after_probe_ms={after_probe_ms:.2f}"
        )
