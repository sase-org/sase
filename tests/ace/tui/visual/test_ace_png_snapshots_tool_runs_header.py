"""ACE PNG snapshots for ToolRun header chips (epic sase-1bt, cutover).

Panel-local header summaries are pre-seeded so these snapshots exercise the
compact identity-header render without depending on async worker timing. The
summary loader and detail surfaces have separate tests; generation is not
approval, so inspect every new PNG.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.bead_touches import BeadTouchEntry
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets.decks.model import DeckId
from sase.ace.tui.widgets.prompt_panel import _agent_display_header_summary_cache
from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
    ALL_DETAIL_CONTEXT_LANES,
    cache_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from sase.core.tool_run import ToolRunGlance, ToolRunNodeSummary
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_tool_runs_png_snapshot_shared import (
    TOOL_RUN_EPOCH_INT,
    local_now_ts,
    pin_tool_run_clocks,
    seed_tool_run_surfaces,
    select_agent,
    tool_run_agent,
    tool_run_brief,
    tool_run_glance,
    tool_run_summary,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _header_agents() -> list[Agent]:
    return [
        tool_run_agent("tr-h-live"),
        tool_run_agent("tr-h-silent"),
        tool_run_agent("tr-h-pass", status="DONE"),
        tool_run_agent("tr-h-new", status="DONE"),
        tool_run_agent("tr-h-known", status="DONE"),
        tool_run_agent("tr-h-undet", status="DONE"),
        tool_run_agent("tr-h-killed", status="DONE"),
        tool_run_agent("tr-h-stopped", status="DONE"),
        tool_run_agent("tr-h-lost", status="DONE"),
    ]


def _header_glances() -> list[ToolRunGlance]:
    return [
        tool_run_glance("a1" * 16, agent="tr-h-live"),
        tool_run_glance(
            "a2" * 16,
            agent="tr-h-silent",
            label="test",
            last_activity_ts=TOOL_RUN_EPOCH_INT - 2 * 86400,
        ),
    ]


def _header_summaries(
    glances: list[ToolRunGlance],
) -> dict[str, ToolRunNodeSummary]:
    settled_ts = TOOL_RUN_EPOCH_INT - 81
    live_by_agent = {glance.agent: glance for glance in glances if glance.agent}
    out: dict[str, ToolRunNodeSummary] = {
        "agent:tr-h-live": tool_run_summary(
            "agent:tr-h-live", live=(live_by_agent["tr-h-live"],)
        ),
        "agent:tr-h-silent": tool_run_summary(
            "agent:tr-h-silent", live=(live_by_agent["tr-h-silent"],)
        ),
    }
    cases = [
        ("tr-h-pass", "pass", {}),
        ("tr-h-new", "new_failures", {"new": 3, "known": 1}),
        ("tr-h-known", "known_only", {"known": 2}),
        ("tr-h-undet", "undetermined", {"unknown": 2}),
        ("tr-h-killed", "killed", {}),
        ("tr-h-stopped", "stopped", {}),
        ("tr-h-lost", "lost", {}),
    ]
    for name, bucket, counts in cases:
        terminal = (
            "signal"
            if bucket == "killed"
            else ("stop_requested" if bucket == "stopped" else None)
        )
        if bucket == "lost":
            terminal = "wrapper_lost"
        out[f"agent:{name}"] = tool_run_summary(
            f"agent:{name}",
            (
                tool_run_brief(
                    f"{name}-run".ljust(32, "0")[:32],
                    bucket=bucket,
                    agent=name,
                    settled_ts=settled_ts,
                    terminal_cause=terminal,
                    **counts,
                ),
            ),
        )
    return out


_HEADER_CHIPS: tuple[tuple[str, str, str], ...] = (
    ("tr-h-live", "7/11", "tool_runs_header_live_120x40"),
    ("tr-h-silent", "silent 48h", "tool_runs_header_silent_120x40"),
    ("tr-h-pass", "✓", "tool_runs_header_pass_120x40"),
    ("tr-h-new", "3 NEW", "tool_runs_header_new_120x40"),
    ("tr-h-known", "known only", "tool_runs_header_known_120x40"),
    ("tr-h-undet", "2 UNKNOWN", "tool_runs_header_undetermined_120x40"),
    ("tr-h-killed", "killed", "tool_runs_header_killed_120x40"),
    ("tr-h-stopped", "stopped", "tool_runs_header_stopped_120x40"),
    ("tr-h-lost", "lost", "tool_runs_header_lost_120x40"),
)


async def test_tool_runs_header_chips_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # These summaries deliberately replace the background context resolver.
    # Freeze its freshness clock too, so a 10 s test run cannot expire the
    # fixture halfway through the chip sequence and introduce a disk-backed
    # assignment row into only the later captures.
    monkeypatch.setattr(
        _agent_display_header_summary_cache,
        "time",
        SimpleNamespace(monotonic=lambda: 0.0),
    )
    pin_tool_run_clocks(monkeypatch)
    # Seed after patch_startup_loaders: the startup helper resets the
    # glance snapshot and stubs the loader seam to None, so seeding first
    # would be clobbered and no header chips would render.
    agents = _header_agents()
    patch_startup_loaders(monkeypatch, agents=agents)
    glances = _header_glances()
    summaries = _header_summaries(glances)
    seed_tool_run_surfaces(
        monkeypatch,
        glances=glances,
        summaries=summaries,
    )

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 9)
        prompt_panel = page.app.query_one("#agent-prompt-panel")
        detail_panel = page.app.query_one("#agent-detail-panel")
        for agent in agents:
            cache_detail_header_summary(
                prompt_panel,
                agent,
                DetailHeaderSummary(
                    tool_run_summary=summaries[f"agent:{agent.agent_name}"],
                    bead_touch_entries=(
                        BeadTouchEntry(bead_id=agent.agent_name or "", own=True),
                    ),
                    ready_lanes=ALL_DETAIL_CONTEXT_LANES,
                ),
            )
        selected = page.app._get_selected_agent()
        if selected is not None:
            detail_panel.update_display(selected)

        def selected_header_text(name: str) -> str:
            selected = page.app._get_selected_agent()
            if selected is None or selected.agent_name != name:
                return ""
            header = getattr(prompt_panel, "_identity_last_published", None)
            compact = getattr(header, "compact", None)
            return str(getattr(compact, "plain", ""))

        for name, fragment, snapshot_name in _HEADER_CHIPS:
            await select_agent(page, name)
            # Let the selection's immediate/debounced detail refresh finish
            # before forcing the pre-seeded full document. Otherwise its
            # header-only partial paint can replace the Main body after the
            # snapshot has observed the new identity.
            await wait_for_visual_idle(page)
            selected = page.app._get_selected_agent()
            if selected is None or selected.agent_name != name:
                raise AssertionError(f"selected agent is not {name!r}")
            # Keep this snapshot focused on header rendering. The list's
            # selection debouncer may still be showing the previous detail
            # subject when the selected row changes; apply the already-seeded
            # fixture immediately, as we did for the initial subject above.
            detail_panel.update_display(selected)
            detail_panel.set_deck_preferred_card(0, "context", DeckId.MAIN)
            detail_panel.show_deck(0, DeckId.MAIN)
            await wait_for_state(
                page,
                lambda: (
                    detail_panel.deck_area.panel(0).deck is DeckId.MAIN
                    and detail_panel._main_deck_document.subject
                    == detail_panel.metadata_identity
                    and detail_panel.deck_area.panel(0).main_view.active_card_id
                    == "context"
                ),
                description="selected agent Main Context document is current",
            )
            await wait_for_visual_idle(page)
            await wait_for_state(
                page,
                lambda name=name, fragment=fragment: (
                    fragment in selected_header_text(name)
                ),
                description=f"selected identity header contains {fragment!r}",
            )
            await wait_for_visual_idle(page)
            ace_png_visual.assert_page_png(
                page, snapshot_name, title=f"ACE tool run header chip ({name})"
            )
