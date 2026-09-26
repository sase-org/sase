"""Sticky-Reply landing and block-cycle benchmark cases."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.app import AceApp
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.util.perf import ENV_PATH
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckLayout
from tests.ace.tui._bench_tui_jk_helpers import (
    _KEYS_PER_SCENARIO,
    _print_table,
    _read_samples,
    _summarize,
    _wait_for_startup,
)

pytest_plugins = ("tests.ace.tui._bench_tui_jk_helpers",)
pytestmark = pytest.mark.slow

_SESSION_COUNT = 3
_SHELLS_PER_SESSION = 10
_REPLY_LINES_PER_SHELL = 500
# Generous ceiling (large-list precedent): catches an order-of-magnitude
# regression without flaking under host contention. The printed table
# carries the tight 16 ms number for the bead record.
_BLOCK_BENCH_P95_BUDGET_MS = 100.0
# Block cycling repaints through the same preferred-set re-show path as
# Ctrl+J/K card cycling; hold it to the generous ceiling, not 16 ms.
_BLOCK_CYCLE_P95_BUDGET_MS = 100.0

_STARTED = datetime(2026, 7, 18, 12, 0, 0)


def _write_shell_content(directory: Path, label: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "response.md").write_text(
        "\n".join(
            f"{label} reply line {index}" for index in range(_REPLY_LINES_PER_SHELL)
        )
        + "\n",
        encoding="utf-8",
    )


def _make_session(tmp_path: Path, index: int) -> Agent:
    members: list[Agent] = []
    for shell in range(_SHELLS_PER_SESSION):
        role = "plan" if shell == 0 else "code"
        suffix = "--plan" if shell == 0 else f"--code-{shell}"
        directory = tmp_path / f"bench-s{index}-{suffix.strip('-')}"
        _write_shell_content(directory, f"s{index}{suffix}")
        members.append(
            Agent(
                agent_type=AgentType.RUNNING,
                cl_name="bench-blocks",
                project_file="/tmp/bench-blocks.sase",
                status="DONE",
                start_time=_STARTED,
                raw_suffix=f"2026071812{index:02d}{shell:02d}",
                artifacts_dir=str(directory),
                response_path=str(directory / "response.md"),
                agent_name=f"bench{index}{suffix}",
                agent_session=f"bench{index}",
                agent_session_role=role,
                role_suffix=suffix,
                model="claude/opus",
                **({"plan_chain_root": True} if shell == 0 else {}),
            )
        )
    root = members[0]
    root.followup_agents = members[1:]
    for member in members[1:]:
        member.agent_session_container = root
    assert root.is_agent_session_container_row is True
    return root


def _install_block_sessions_fixture(
    app: AceApp, tmp_path: Path, count: int = _SESSION_COUNT
) -> list[Agent]:
    sessions = [_make_session(tmp_path, index) for index in range(count)]
    app._agents = list(sessions)
    app._agents_with_children = list(sessions)
    app._fold_counts = {}
    app._group_fold_registry = AgentGroupFoldRegistry()
    app._panel_group = AgentPanelGroup.from_agents(sessions)
    app._agent_panels_grouped = False
    app._current_group_key = None
    app.current_idx = 0
    app._invalidate_agent_panel_cache()
    return sessions


def _sticky_layout_name(layout: DeckLayout) -> str:
    return "LEFT_RIGHT" if layout is DeckLayout.LEFT_RIGHT else "SINGLE"


async def _run_sticky_arm(
    tmp_path: Path,
    log_path: Path,
    *,
    layout: DeckLayout,
) -> dict[str, dict[str, float]]:
    arm = "sticky-Reply-blocks"
    arm_log = log_path.parent / f"{arm}-{_sticky_layout_name(layout)}.jsonl"
    if arm_log.exists():
        arm_log.unlink()
    previous = os.environ.get(ENV_PATH)
    os.environ[ENV_PATH] = str(arm_log)
    try:
        app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
        async with app.run_test() as pilot:
            await _wait_for_startup(app, pilot)
            await pilot.press("ctrl+l")
            await pilot.pause()
            _install_block_sessions_fixture(app, tmp_path)
            app._refresh_agents_display(list_changed=True, defer_detail=True)
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            if layout is DeckLayout.LEFT_RIGHT:
                detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
                await pilot.pause()
            # Stick both panels' preferred card to Reply so j/k lands
            # on the block-paged card on every new subject.
            detail.set_deck_preferred_card(0, "reply")
            detail.set_deck_preferred_card(1, "reply")
            app._refresh_agents_display(list_changed=True, defer_detail=True)
            await pilot.pause()
            # Warm-up round settles debounce and measure caches.
            for _ in range(_KEYS_PER_SCENARIO):
                await pilot.press("j")
                await pilot.pause(0.01)
            for _ in range(_KEYS_PER_SCENARIO):
                await pilot.press("j")
                await pilot.pause(0.01)
            for _ in range(_KEYS_PER_SCENARIO):
                await pilot.press("k")
                await pilot.pause(0.01)
    finally:
        if previous is None:
            os.environ.pop(ENV_PATH, None)
        else:
            os.environ[ENV_PATH] = previous
    samples = [
        s
        for s in _read_samples(arm_log)
        if s.get("tab") == "agents" and str(s.get("action")) in {"next", "prev"}
    ]
    summary = _summarize(samples)
    _print_table(f"{arm} ({_sticky_layout_name(layout)}):", summary)
    return summary


async def test_bench_sticky_reply_heavy_sessions(
    tmp_path: Path, _perf_jsonl: Path
) -> None:
    """Time sticky-Reply j/k across heavy sessions."""
    for layout in (DeckLayout.SINGLE, DeckLayout.LEFT_RIGHT):
        summary = await _run_sticky_arm(tmp_path, _perf_jsonl, layout=layout)
        name = _sticky_layout_name(layout)
        assert summary, f"no j/k samples captured ({name})"
        assert all(
            stats["p95"] < _BLOCK_BENCH_P95_BUDGET_MS for stats in summary.values()
        ), f"sticky-Reply ({name}) exceeded budget: {summary}"


async def test_bench_block_cycle_paged(tmp_path: Path, _perf_jsonl: Path) -> None:
    """Time paged block cycling over a 10-shell sticky Reply."""
    from sase.ace.tui.agent_decks_settings import AgentDecksSettings

    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()
        _install_block_sessions_fixture(app, tmp_path, count=1)
        app._agent_decks_settings = AgentDecksSettings(
            spread_max_screens=0, block_spread_max_screens=0
        )
        app._refresh_agents_display(list_changed=True, defer_detail=True)
        await pilot.pause()
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        # Stick the preferred card to Reply so the paged block card survives
        # deferred refreshes, exactly as the sticky-Reply bench arm does.
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
        document = panel._main_document
        assert any(bool(card.has_block_navigation) for card in document.cards), (
            "bench session has no navigable Reply blocks"
        )
        # Warm up CSS/layout caches: the first swaps pay full
        # preferred-set re-show costs shared with Ctrl+J/K.
        for _ in range(10):
            assert detail.cycle_focused_card_block(-1) is True
            await pilot.pause(0.01)
        for index in range(_KEYS_PER_SCENARIO):
            direction = -1 if index % 2 == 0 else 1
            app._jk_perf_begin("cycle_block")
            assert detail.cycle_focused_card_block(direction) is True
            jk_perf = app._jk_perf
            if jk_perf is not None:
                app.call_after_refresh(jk_perf.mark_painted)
            await pilot.pause(0.01)
    samples = [
        s for s in _read_samples(_perf_jsonl) if str(s.get("action")) == "cycle_block"
    ]
    summary = _summarize(samples)
    _print_table("Block-cycle (paged):", summary)
    assert summary, "no cycle_block samples captured"
    # Median, not p95: the host's scheduler stalls land in the tail (the
    # link-rail bench documents the same noise), while the median catches
    # a genuine 2x page-swap regression.
    assert summary["cycle_block"]["p50"] < _BLOCK_CYCLE_P95_BUDGET_MS, summary
