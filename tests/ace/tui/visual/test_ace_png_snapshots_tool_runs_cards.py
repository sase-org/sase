"""ACE PNG snapshots for ToolRun detail cards (epic sase-1bt, cutover).

Every surface reads deterministic fixtures through one loader seam each
for glance, node summaries, and run detail, with pinned clocks and no
SQLite. Generation is not approval: inspect every new PNG.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.tool_runs.detail import LoadedToolRunDetail
from sase.core.tool_run import ToolRunBrief, ToolRunGlance, ToolRunNodeSummary
from sase.core.tool_run_views import (
    ToolRunDetail,
    ToolRunDetailStage,
    ToolRunDetailStageCounts,
    ToolRunDetailTriageItem,
    ToolRunLogMetadata,
)
from sase.tool.logs import _ToolRunLogTail
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_tool_runs_png_snapshot_shared import (
    TOOL_RUN_EPOCH_INT,
    pin_tool_run_clocks,
    seed_tool_run_surfaces,
    select_agent,
    show_runs_card,
    tool_run_agent,
    tool_run_brief,
    tool_run_glance,
    tool_run_summary,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _check_stages(base_ms: int) -> tuple[ToolRunDetailStage, ...]:
    return (
        ToolRunDetailStage(
            description="fmt (python)",
            started_ms=base_ms,
            finished_ms=base_ms + 300,
            elapsed_ms=300,
            exit_code=0,
        ),
        ToolRunDetailStage(
            description="lint (ruff)",
            started_ms=base_ms + 300,
            finished_ms=base_ms + 4400,
            elapsed_ms=4100,
            exit_code=0,
        ),
        ToolRunDetailStage(
            description="lint (mypy)",
            started_ms=base_ms + 4400,
            finished_ms=base_ms + 67400,
            elapsed_ms=63000,
            exit_code=0,
        ),
        ToolRunDetailStage(
            description="lint (symvision)",
            started_ms=base_ms + 67400,
            finished_ms=base_ms + 134400,
            elapsed_ms=67000,
            exit_code=1,
            counts=ToolRunDetailStageCounts(new=2),
        ),
        ToolRunDetailStage(
            description="keep-sorted",
            started_ms=base_ms + 134400,
            finished_ms=base_ms + 135200,
            elapsed_ms=800,
            exit_code=0,
        ),
        ToolRunDetailStage(
            description="test (scoped)",
            started_ms=base_ms + 135200,
            finished_ms=base_ms + 226200,
            elapsed_ms=91000,
            exit_code=1,
            counts=ToolRunDetailStageCounts(new=1, known=1),
        ),
    )


def _check_items() -> tuple[ToolRunDetailTriageItem, ...]:
    return (
        ToolRunDetailTriageItem(
            stage_key="lint (mypy)",
            display="_tree.py:622 Name already defined",
            occurrences=35,
            witness_runs=35,
            witness_agents=33,
            item_class="NEW",
            locator_paths=("_tree.py:622",),
            first_seen_ts=TOOL_RUN_EPOCH_INT - 86400,
            last_seen_ts=TOOL_RUN_EPOCH_INT - 359,
        ),
        ToolRunDetailTriageItem(
            stage_key="test (scoped)",
            display="test_check rerun mismatch",
            occurrences=12,
            witness_runs=9,
            witness_agents=7,
            item_class="KNOWN",
            locator_paths=("tests/test_x.py:41",),
            first_seen_ts=TOOL_RUN_EPOCH_INT - 3 * 86400,
            last_seen_ts=TOOL_RUN_EPOCH_INT - 359,
        ),
    )


def _failed_detail(brief: ToolRunBrief) -> LoadedToolRunDetail:
    base_ms = (brief.created_ts or TOOL_RUN_EPOCH_INT) * 1000
    detail = ToolRunDetail(
        store_exists=True,
        found=True,
        display_argv=("just", "check"),
        stages=_check_stages(base_ms),
        triage_items=_check_items(),
        child_runs=(
            tool_run_brief(
                "81ef0cb1" + "0" * 24,
                label="test",
                bucket="pass",
                agent=brief.agent,
            ),
        ),
        logs=ToolRunLogMetadata(),
        brief=brief,
    )
    tail = _ToolRunLogTail(
        availability="available",
        source="run",
        lines=tuple(f"check output line {index}" for index in range(1, 13)),
        total_bytes=1200,
        truncated=False,
    )
    return LoadedToolRunDetail(run_id=brief.run_id, detail=detail, tail=tail)


def _card_agents() -> list[Agent]:
    agents = [
        tool_run_agent("tr-c-failed", status="DONE"),
        tool_run_agent("tr-c-live"),
        tool_run_agent("tr-c-killed", status="DONE"),
        tool_run_agent("tr-c-pass", status="DONE"),
        tool_run_agent("tr-c-pruned", status="DONE"),
        tool_run_agent(
            "tr-c-mon",
            status="MONITORING",
            agent_session_role="monitor",
            role_suffix="--mon",
            monitor_id="tr-mon",
        ),
    ]
    return agents


def _card_glances() -> list[ToolRunGlance]:
    return [
        tool_run_glance(
            "c1" + "0" * 30,
            agent="tr-c-live",
            created_ts=TOOL_RUN_EPOCH_INT - 133,
        ),
    ]


def _card_summaries() -> dict[str, ToolRunNodeSummary]:
    failed_id = "6c3d5107" + "0" * 24
    failed = tool_run_brief(
        failed_id, bucket="new_failures", new=3, known=1, agent="tr-c-failed"
    )
    killed = tool_run_brief(
        "k1" + "0" * 30,
        bucket="killed",
        terminal_cause="signal",
        agent="tr-c-killed",
        duration_ms=540000,
    )
    passed = tool_run_brief("p1" + "0" * 30, bucket="pass", agent="tr-c-pass")
    pruned_id = "d1" + "0" * 30
    pruned = tool_run_brief(
        pruned_id, bucket="new_failures", new=1, agent="tr-c-pruned"
    )
    object.__setattr__(pruned, "detail_pruned", True)
    mon_brief = tool_run_brief(
        "m1" + "0" * 30,
        bucket="new_failures",
        new=2,
        agent="tr-starter",
        owner_kind="monitor",
        owner_id="tr-mon",
    )
    live_glance = tool_run_glance(
        "c1" + "0" * 30,
        agent="tr-c-live",
        created_ts=TOOL_RUN_EPOCH_INT - 133,
    )
    return {
        "agent:tr-c-failed": tool_run_summary("agent:tr-c-failed", (failed,)),
        "agent:tr-c-live": tool_run_summary("agent:tr-c-live", live=(live_glance,)),
        "agent:tr-c-killed": tool_run_summary("agent:tr-c-killed", (killed,)),
        "agent:tr-c-pass": tool_run_summary("agent:tr-c-pass", (passed,)),
        "agent:tr-c-pruned": tool_run_summary("agent:tr-c-pruned", (pruned,)),
        "monitor:tr-mon": tool_run_summary("monitor:tr-mon", (mon_brief,)),
    }


def _card_details() -> dict[str, LoadedToolRunDetail]:
    summaries = _card_summaries()
    failed = summaries["agent:tr-c-failed"].runs[0]
    killed = summaries["agent:tr-c-killed"].runs[0]
    passed = summaries["agent:tr-c-pass"].runs[0]
    pruned = summaries["agent:tr-c-pruned"].runs[0]
    mon = summaries["monitor:tr-mon"].runs[0]
    live_detail = ToolRunDetail(
        store_exists=True,
        found=True,
        display_argv=("just", "check"),
        stages=(
            ToolRunDetailStage(
                description="fmt (python)",
                started_ms=(TOOL_RUN_EPOCH_INT - 133) * 1000,
                finished_ms=(TOOL_RUN_EPOCH_INT - 132) * 1000,
                elapsed_ms=1000,
                exit_code=0,
            ),
            ToolRunDetailStage(
                description="test (scoped)",
                started_ms=(TOOL_RUN_EPOCH_INT - 132) * 1000,
                incomplete=True,
            ),
        ),
        expected_stages=(),
        brief=tool_run_brief(
            "c1" + "0" * 30,
            bucket="undetermined",
            state="running",
            created_ts=TOOL_RUN_EPOCH_INT - 133,
            settled_ts=None,
            duration_ms=None,
            agent="tr-c-live",
        ),
    )
    pruned_detail = ToolRunDetail(
        store_exists=True,
        found=True,
        display_argv=("just", "check"),
        detail_pruned=True,
        brief=pruned,
    )
    simple = {
        killed.run_id: ToolRunDetail(
            store_exists=True,
            found=True,
            display_argv=("just", "check"),
            stages=(),
            brief=killed,
        ),
        passed.run_id: ToolRunDetail(
            store_exists=True,
            found=True,
            display_argv=("sase", "tool", "run", "test"),
            stages=(),
            brief=passed,
        ),
        mon.run_id: ToolRunDetail(
            store_exists=True,
            found=True,
            display_argv=("just", "check"),
            stages=(),
            brief=mon,
        ),
    }
    out = {
        failed.run_id: _failed_detail(failed),
        ("c1" + "0" * 30): LoadedToolRunDetail(
            run_id="c1" + "0" * 30,
            detail=live_detail,
            tail=_ToolRunLogTail(),
            live=True,
        ),
        pruned.run_id: LoadedToolRunDetail(
            run_id=pruned.run_id,
            detail=pruned_detail,
            tail=_ToolRunLogTail(
                availability="pruned",
                source="none",
                lines=(),
                total_bytes=0,
                truncated=False,
            ),
        ),
    }
    for run_id, detail in simple.items():
        out[run_id] = LoadedToolRunDetail(run_id=run_id, detail=detail, tail=None)
    return out


_CARD_CASES: tuple[tuple[str, str, str], ...] = (
    ("tr-c-failed", "3 NEW", "tool_runs_card_failed_120x40"),
    ("tr-c-live", "7/11", "tool_runs_card_live_120x40"),
    ("tr-c-killed", "killed", "tool_runs_card_killed_120x40"),
    ("tr-c-pass", "✓", "tool_runs_card_pass_120x40"),
    ("tr-c-pruned", "detail pruned", "tool_runs_card_pruned_120x40"),
    ("tr-c-mon", "→ monitor tr-mon", "tool_runs_card_monitor_120x40"),
)


async def test_tool_runs_card_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_tool_run_clocks(monkeypatch)
    # Freeze the 1 Hz live repaint so the live card converges: the initial
    # worker paint still renders progress/elapsed, only the per-second
    # re-render is suppressed (tick gating itself is unit-tested).
    from sase.ace.tui.widgets.decks.tool_runs import widget_live as runs_live_module

    monkeypatch.setattr(runs_live_module, "want_live_tick", lambda **kw: False)
    seed_tool_run_surfaces(
        monkeypatch,
        glances=_card_glances(),
        summaries=_card_summaries(),
        details=_card_details(),
    )
    patch_startup_loaders(monkeypatch, agents=_card_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 6)
        for name, fragment, snapshot_name in _CARD_CASES:
            await select_agent(page, name)
            await show_runs_card(page)
            await wait_for_svg_contains(page, fragment, timeout=60.0)
            await wait_for_visual_idle(page)
            ace_png_visual.assert_page_png(
                page, snapshot_name, title=f"ACE tool runs card ({name})"
            )
        await page.press("p")
        await page.expect_modal("DeckPickerModal")
        await wait_for_svg_contains(page, "Switch deck")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page, "tool_runs_picker_120x40", title="ACE tool runs deck picker"
        )
