"""ACE PNG snapshots for ToolRun TUI surfaces (epic sase-1bt, cutover).

Every surface reads deterministic fixtures through one loader seam each
for glance, node summaries, and run detail, with pinned clocks and no
SQLite. Generation is not approval: inspect every new PNG.
"""

from __future__ import annotations

import time as _real_time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.tool_runs.detail import LoadedToolRunDetail
from sase.ace.tui.tool_runs.snapshot import _build_snapshot
from sase.core.tool_run import ToolRunBrief, ToolRunGlance, ToolRunNodeSummary
from sase.core.tool_run import ToolRunVerdictSummary
from sase.core.tool_run_views import (
    ToolRunDetail,
    ToolRunDetailStage,
    ToolRunDetailStageCounts,
    ToolRunDetailTriageItem,
    ToolRunLogMetadata,
)
from sase.tool.logs import ToolRunLogTail
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_NOW = datetime(2026, 7, 28, 12, 10, tzinfo=UTC)
_E = 1785239400.0
_EI = 1785239400


# Row chips read a naive local now. The visual conftest pins TZ=UTC in a
# function-scoped fixture (after module import), so fixture activity stamps
# must use the same naive conversion the app performs, computed lazily at
# fixture-build time rather than at module import.
def _local_now_ts() -> float:
    return _NOW.replace(tzinfo=None).timestamp()


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return _NOW if tz is None else _NOW.astimezone(tz)


class _FakeTime:
    """Pin wall-clock reads while leaving monotonic clocks alone."""

    @staticmethod
    def time() -> float:
        return _E

    monotonic = staticmethod(_real_time.monotonic)
    perf_counter = staticmethod(_real_time.perf_counter)
    sleep = staticmethod(_real_time.sleep)
    tzname = staticmethod(_real_time.tzname)


def _pin_tool_run_clocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every clock the ToolRun surfaces read (no SQLite, no drift)."""
    from sase.ace.tui.models import agent_time as agent_time_module
    from sase.ace.tui.widgets import _agent_list_render_agent_status as row_module
    from sase.ace.tui.tool_runs import header_chip as header_chip_module
    from sase.ace.tui.tool_runs import links as links_module
    from sase.ace.tui.widgets.decks.tool_runs import view as runs_view_module
    from sase.ace.tui.widgets.prompt_panel import _agent_display_header

    pin_agents_visual_now(monkeypatch, _NOW.replace(tzinfo=None))
    monkeypatch.setattr(_agent_display_header, "DateTime", _FixedDateTime)
    from sase.ace.tui.widgets.prompt_panel import _agent_context_common

    monkeypatch.setattr(_agent_context_common, "get_timezone", lambda: ZoneInfo("UTC"))
    naive = _NOW.replace(tzinfo=None)
    monkeypatch.setattr(row_module, "local_now", lambda: naive)
    monkeypatch.setattr(agent_time_module, "local_now", lambda: naive)
    for module in (header_chip_module, links_module, runs_view_module):
        monkeypatch.setattr(module, "time", _FakeTime)


def _verdict(bucket: str, **counts: Any) -> ToolRunVerdictSummary:
    return ToolRunVerdictSummary(
        bucket=bucket,
        new=int(counts.get("new", 0)),
        known=int(counts.get("known", 0)),
        flaky=int(counts.get("flaky", 0)),
        unknown=int(counts.get("unknown", 0)),
        reasons=tuple(counts.get("reasons", ())),
    )


def _brief(
    run_id: str,
    label: str = "check",
    bucket: str = "pass",
    *,
    state: str = "succeeded",
    created_ts: int = _EI - 600,
    settled_ts: int | None = _EI - 359,
    duration_ms: int | None = 252000,
    typical_ms: int | None = 253000,
    agent: str | None = "tr-failed",
    owner_kind: str | None = None,
    owner_id: str | None = None,
    terminal_cause: str | None = None,
    tool_name: str | None = "check",
    launch_mode: str | None = "inline",
    bead: str | None = "sase-1b2.20",
    workspace: str | None = "13",
    **counts: Any,
) -> ToolRunBrief:
    return ToolRunBrief(
        run_id=run_id,
        label=label,
        state=state,
        created_ts=created_ts,
        verdict=_verdict(bucket, **counts),
        detail_pruned=False,
        tool_name=tool_name,
        launch_mode=launch_mode,
        terminal_cause=terminal_cause,
        agent=agent,
        workspace=workspace,
        bead=bead,
        owner_kind=owner_kind,
        owner_id=owner_id,
        running_ts=created_ts,
        settled_ts=settled_ts,
        duration_ms=duration_ms,
        typical_ms=typical_ms,
    )


def _glance(
    run_id: str,
    *,
    agent: str | None = "tr-live",
    owner_kind: str | None = None,
    owner_id: str | None = None,
    state: str = "running",
    label: str = "check",
    created_ts: int = _EI - 133,
    last_activity_ts: int | None = None,
    stages_done: int = 6,
    stages_expected: int | None = 11,
    parent_run_id: str | None = None,
    stop_requested: bool = False,
    typical_ms: int | None = 253000,
) -> ToolRunGlance:
    if last_activity_ts is None:
        last_activity_ts = int(_local_now_ts()) - 3
    return ToolRunGlance(
        run_id=run_id,
        label=label,
        state=state,
        created_ts=created_ts,
        last_activity_ts=int(last_activity_ts),
        stages_done=stages_done,
        stop_requested=stop_requested,
        agent=agent,
        owner_kind=owner_kind,
        owner_id=owner_id,
        parent_run_id=parent_run_id,
        running_ts=created_ts,
        current_stage=None,
        stages_expected=stages_expected,
        typical_ms=typical_ms,
    )


def _summary(
    key: str,
    briefs: tuple[ToolRunBrief, ...] = (),
    live: tuple[ToolRunGlance, ...] = (),
) -> ToolRunNodeSummary:
    return ToolRunNodeSummary(
        key=key,
        total_runs=len(briefs),
        live=live,
        latest_by_tool=briefs,
        runs=briefs,
    )


def _agent(name: str, status: str = "RUNNING", **over: Any) -> Agent:
    fields: dict[str, Any] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": "/workspace/sase/visual_project.sase",
        "status": status,
        "start_time": datetime(2026, 7, 28, 12, 0),
        "run_start_time": datetime(2026, 7, 28, 12, 0),
        "raw_suffix": f"20260728120000-{name}",
        "agent_name": name,
        "llm_provider": "codex",
        "model": "gpt-5.6",
        "workspace_num": 13,
    }
    fields.update(over)
    return Agent(**fields)


def _seed_tool_run_surfaces(
    monkeypatch: pytest.MonkeyPatch,
    *,
    glances: list[ToolRunGlance],
    summaries: dict[str, ToolRunNodeSummary],
    details: dict[str, LoadedToolRunDetail] | None = None,
) -> None:
    """Seed the glance/summary/detail seams with fixed fixtures (no I/O)."""
    from sase.ace.tui.tool_runs import detail as detail_module
    from sase.ace.tui.tool_runs import loader as loader_module
    from sase.ace.tui.tool_runs import snapshot as snapshot_module
    from sase.ace.tui.tool_runs import summaries as summaries_module
    from sase.ace.tui.widgets.decks.tool_runs import view as runs_view_module

    snap = _build_snapshot(list(glances), generation=3)
    snapshot_module._set_snapshot(snap)
    monkeypatch.setattr(snapshot_module, "load_glance_blocking", lambda **kw: snap)
    monkeypatch.setattr(loader_module, "load_glance_blocking", lambda **kw: snap)
    monkeypatch.setattr(
        summaries_module,
        "_load_node_summary_blocking",
        lambda selector: summaries.get(selector.key),
    )
    detail_map = details or {}

    def _load(
        run_id: str,
        brief: Any = None,
        store_token: Any = None,
        **kw: Any,
    ) -> LoadedToolRunDetail | None:
        return detail_map.get(str(run_id))

    monkeypatch.setattr(detail_module, "load_tool_run_detail_blocking", _load)
    monkeypatch.setattr(runs_view_module, "load_tool_run_detail_blocking", _load)


def _rows_agents() -> list[Agent]:
    return [
        _agent("tr-live"),
        _agent("tr-silent"),
        _agent("tr-start"),
        _agent("tr-plus"),
    ]


def _rows_glances() -> list[ToolRunGlance]:
    return [
        _glance("11" * 16, agent="tr-live"),
        _glance(
            "22" * 16,
            agent="tr-silent",
            label="test",
            last_activity_ts=int(_local_now_ts()) - 2 * 86400,
        ),
        _glance("33" * 16, agent="tr-start", state="created", stages_done=0),
        _glance("44" * 16, agent="tr-plus", stages_done=2),
        _glance("55" * 16, agent="tr-plus", label="lint", stages_done=1),
    ]


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [
        ((120, 40), "tool_runs_rows_120x40"),
        ((80, 40), "tool_runs_rows_80x40"),
        ((60, 40), "tool_runs_rows_60x40"),
    ],
)
async def test_tool_runs_rows_png_snapshots(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_tool_run_clocks(monkeypatch)
    _seed_tool_run_surfaces(monkeypatch, glances=_rows_glances(), summaries={})
    patch_startup_loaders(monkeypatch, agents=_rows_agents())

    async with AcePage(query='"visual"', patches=patches(), size=size) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        await wait_for_svg_contains(page, "⚒ check 7/11")
        await wait_for_svg_contains(page, "silent 48h")
        await wait_for_svg_contains(page, "starting")
        await wait_for_svg_contains(page, "+1")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page, snapshot_name, title=f"ACE tool run rows ({size[0]}x{size[1]})"
        )


def _header_agents() -> list[Agent]:
    return [
        _agent("tr-h-live"),
        _agent("tr-h-silent"),
        _agent("tr-h-pass", status="DONE"),
        _agent("tr-h-new", status="DONE"),
        _agent("tr-h-known", status="DONE"),
        _agent("tr-h-undet", status="DONE"),
        _agent("tr-h-killed", status="DONE"),
        _agent("tr-h-stopped", status="DONE"),
        _agent("tr-h-lost", status="DONE"),
    ]


def _header_glances() -> list[ToolRunGlance]:
    return [
        _glance("a1" * 16, agent="tr-h-live"),
        _glance(
            "a2" * 16,
            agent="tr-h-silent",
            label="test",
            last_activity_ts=int(_local_now_ts()) - 2 * 86400,
        ),
    ]


def _header_summaries() -> dict[str, ToolRunNodeSummary]:
    settled_ts = _EI - 81
    out: dict[str, ToolRunNodeSummary] = {
        "agent:tr-h-live": _summary("agent:tr-h-live"),
        "agent:tr-h-silent": _summary("agent:tr-h-silent"),
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
        out[f"agent:{name}"] = _summary(
            f"agent:{name}",
            (
                _brief(
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
    _pin_tool_run_clocks(monkeypatch)
    _seed_tool_run_surfaces(
        monkeypatch,
        glances=_header_glances(),
        summaries=_header_summaries(),
    )
    patch_startup_loaders(monkeypatch, agents=_header_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 9)
        for name, fragment, snapshot_name in _HEADER_CHIPS:
            await _select_agent(page, name)
            await wait_for_svg_contains(page, fragment)
            await wait_for_visual_idle(page)
            ace_png_visual.assert_page_png(
                page, snapshot_name, title=f"ACE tool run header chip ({name})"
            )


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
            first_seen_ts=_EI - 86400,
            last_seen_ts=_EI - 359,
        ),
        ToolRunDetailTriageItem(
            stage_key="test (scoped)",
            display="test_check rerun mismatch",
            occurrences=12,
            witness_runs=9,
            witness_agents=7,
            item_class="KNOWN",
            locator_paths=("tests/test_x.py:41",),
            first_seen_ts=_EI - 3 * 86400,
            last_seen_ts=_EI - 359,
        ),
    )


def _failed_detail(brief: ToolRunBrief) -> LoadedToolRunDetail:
    base_ms = (brief.created_ts or _EI) * 1000
    detail = ToolRunDetail(
        store_exists=True,
        found=True,
        display_argv=("just", "check"),
        stages=_check_stages(base_ms),
        triage_items=_check_items(),
        child_runs=(
            _brief(
                "81ef0cb1" + "0" * 24,
                label="test",
                bucket="pass",
                agent=brief.agent,
            ),
        ),
        logs=ToolRunLogMetadata(),
        brief=brief,
    )
    tail = ToolRunLogTail(
        availability="available",
        source="run",
        lines=tuple(f"check output line {index}" for index in range(1, 13)),
        total_bytes=1200,
        truncated=False,
    )
    return LoadedToolRunDetail(run_id=brief.run_id, detail=detail, tail=tail)


def _card_agents() -> list[Agent]:
    agents = [
        _agent("tr-c-failed", status="DONE"),
        _agent("tr-c-live"),
        _agent("tr-c-killed", status="DONE"),
        _agent("tr-c-pass", status="DONE"),
        _agent("tr-c-pruned", status="DONE"),
        _agent(
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
        _glance(
            "c1" + "0" * 30,
            agent="tr-c-live",
            created_ts=_EI - 133,
        ),
    ]


def _card_summaries() -> dict[str, ToolRunNodeSummary]:
    failed_id = "6c3d5107" + "0" * 24
    failed = _brief(
        failed_id, bucket="new_failures", new=3, known=1, agent="tr-c-failed"
    )
    killed = _brief(
        "k1" + "0" * 30,
        bucket="killed",
        terminal_cause="signal",
        agent="tr-c-killed",
        duration_ms=540000,
    )
    passed = _brief("p1" + "0" * 30, bucket="pass", agent="tr-c-pass")
    pruned_id = "d1" + "0" * 30
    pruned = _brief(pruned_id, bucket="new_failures", new=1, agent="tr-c-pruned")
    object.__setattr__(pruned, "detail_pruned", True)
    mon_brief = _brief(
        "m1" + "0" * 30,
        bucket="new_failures",
        new=2,
        agent="tr-starter",
        owner_kind="monitor",
        owner_id="tr-mon",
    )
    live_glance = _glance(
        "c1" + "0" * 30,
        agent="tr-c-live",
        created_ts=_EI - 133,
    )
    return {
        "agent:tr-c-failed": _summary("agent:tr-c-failed", (failed,)),
        "agent:tr-c-live": _summary("agent:tr-c-live", live=(live_glance,)),
        "agent:tr-c-killed": _summary("agent:tr-c-killed", (killed,)),
        "agent:tr-c-pass": _summary("agent:tr-c-pass", (passed,)),
        "agent:tr-c-pruned": _summary("agent:tr-c-pruned", (pruned,)),
        "monitor:tr-mon": _summary("monitor:tr-mon", (mon_brief,)),
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
                started_ms=(_EI - 133) * 1000,
                finished_ms=(_EI - 132) * 1000,
                elapsed_ms=1000,
                exit_code=0,
            ),
            ToolRunDetailStage(
                description="test (scoped)",
                started_ms=(_EI - 132) * 1000,
                incomplete=True,
            ),
        ),
        expected_stages=(),
        brief=_brief(
            "c1" + "0" * 30,
            bucket="undetermined",
            state="running",
            created_ts=_EI - 133,
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
            tail=ToolRunLogTail(),
            live=True,
        ),
        pruned.run_id: LoadedToolRunDetail(
            run_id=pruned.run_id,
            detail=pruned_detail,
            tail=ToolRunLogTail(
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


async def _show_runs_card(page: AcePage) -> None:
    page.app.action_show_tool_runs_card()
    await wait_for_visual_idle(page)


async def _select_agent(page: AcePage, name: str, *, max_steps: int = 12) -> None:
    """Press j/k until the selected agent names *name* (list order varies)."""
    for _ in range(max_steps + 1):
        selected = page.app._get_selected_agent()
        if selected is not None and (
            getattr(selected, "agent_name", None) == name
            or getattr(selected, "cl_name", None) == name
        ):
            return
        await page.press("j")
    raise AssertionError(f"could not select agent {name!r}")


async def test_tool_runs_card_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_tool_run_clocks(monkeypatch)
    # Freeze the 1 Hz live repaint so the live card converges: the initial
    # worker paint still renders progress/elapsed, only the per-second
    # re-render is suppressed (tick gating itself is unit-tested).
    from sase.ace.tui.widgets.decks.tool_runs import view as runs_view_module

    monkeypatch.setattr(runs_view_module, "want_live_tick", lambda **kw: False)
    _seed_tool_run_surfaces(
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
            await _select_agent(page, name)
            await _show_runs_card(page)
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


# NOTE: no 80-column Runs card snapshot. At 80 cols the responsive layout
# is list-only (the detail deck is hidden), so narrow widths cover rows
# (see test_tool_runs_rows_png_snapshots); the card is covered at 120.
async def test_tool_runs_session_rail_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_tool_run_clocks(monkeypatch)
    root = _agent(
        "tr-sess",
        agent_session="tr-sess",
        agent_session_role="root",
    )
    child_a = _agent(
        "tr-sess--a",
        status="DONE",
        agent_session="tr-sess",
        agent_session_role="code",
        role_suffix="--a",
        parent_timestamp=root.raw_suffix,
    )
    child_b = _agent(
        "tr-sess--b",
        status="DONE",
        agent_session="tr-sess",
        agent_session_role="reviewer",
        role_suffix="--b",
        parent_timestamp=root.raw_suffix,
    )
    root.followup_agents = [child_a, child_b]
    briefs = (
        _brief("s1" + "0" * 30, bucket="new_failures", new=1, agent="tr-sess--a"),
        _brief("s2" + "0" * 30, bucket="known_only", known=2, agent="tr-sess--b"),
        _brief("s3" + "0" * 30, bucket="pass", agent="tr-sess"),
    )
    from sase.ace.tui.tool_runs.summaries import selector_for_agent

    key = selector_for_agent(root)
    assert key is not None
    summary = _summary(key.key, briefs)
    details = {
        brief.run_id: LoadedToolRunDetail(
            run_id=brief.run_id,
            detail=ToolRunDetail(
                store_exists=True,
                found=True,
                display_argv=("just", "check"),
                stages=(),
                brief=brief,
            ),
            tail=None,
        )
        for brief in briefs
    }
    _seed_tool_run_surfaces(
        monkeypatch, glances=[], summaries={key.key: summary}, details=details
    )
    patch_startup_loaders(monkeypatch, agents=[root, child_a, child_b])

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await _select_agent(page, "tr-sess")
        await _show_runs_card(page)
        await wait_for_svg_contains(page, "s1000000")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "tool_runs_card_session_120x40",
            title="ACE tool runs card session rail",
        )
        page.app.action_toggle_deck_split_right()
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "tool_runs_split_120x40",
            title="ACE tools reply split",
        )


def _admin_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seed the Admin Tools pane data sources with fixed fixtures."""
    import sase.config.tools as config_tools
    from sase.ace.tui.actions.agents import _tool_run_actions as actions_module
    from sase.ace.tui.modals import tool_runs_pane as pane_module
    from sase.core import tool_run as core_tool_run

    briefs = (
        _brief("6c3d5107" + "0" * 24, bucket="new_failures", new=3, known=1),
        _brief(
            "22" + "0" * 30,
            label="test",
            bucket="pass",
            agent="tr-other",
            settled_ts=_EI - 1500,
        ),
    )
    live = _glance("c1" + "0" * 30)
    monkeypatch.setattr(
        core_tool_run,
        "tool_run_live_glance",
        lambda *a, **kw: SimpleNamespace(runs=[live], silent_after_s=60),
    )
    monkeypatch.setattr(
        core_tool_run,
        "tool_run_briefs",
        lambda request: SimpleNamespace(runs=list(briefs)),
    )
    monkeypatch.setattr(
        core_tool_run,
        "tool_run_failures",
        lambda request: {
            "groups": [
                {
                    "class": "NEW",
                    "tool": "check",
                    "stage_key": "lint (mypy)",
                    "display": "_tree.py:622 Name already defined",
                    "runs": 35,
                    "agents": 33,
                },
                {
                    "class": "KNOWN",
                    "tool": "check",
                    "stage_key": "test (scoped)",
                    "display": "test_check rerun mismatch",
                    "runs": 12,
                    "agents": 7,
                },
            ]
        },
    )
    monkeypatch.setattr(
        config_tools,
        "load_project_tool_catalog_at",
        lambda root: SimpleNamespace(
            project="sase",
            entries=[
                SimpleNamespace(name="check", digest="digest-check"),
                SimpleNamespace(name="test", digest="digest-test"),
            ],
        ),
    )
    monkeypatch.setattr(
        core_tool_run,
        "tool_run_summary",
        lambda request: {
            "last": {"bucket": "new_failures"},
            "typical_duration_ms": 252000,
            "typical_sample_count": 41,
        },
    )
    monkeypatch.setattr(
        actions_module, "primary_checkout_root", lambda project: "/workspace/sase"
    )
    monkeypatch.setattr(pane_module, "time", _FakeTime)


async def test_tool_runs_admin_pane_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_tool_run_clocks(monkeypatch)
    _admin_seams(monkeypatch)
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        page.app.screen.action_focus_center_tab(7)
        await wait_for_svg_contains(page, "Catalog")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page, "tool_runs_admin_runs_120x40", title="ACE admin tools runs"
        )
        await page.press("right_square_bracket")
        await wait_for_svg_contains(page, "33 agents")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page, "tool_runs_admin_failures_120x40", title="ACE admin tools failures"
        )
        await page.press("right_square_bracket")
        await wait_for_svg_contains(page, "LAST new_failures")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page, "tool_runs_admin_catalog_120x40", title="ACE admin tools catalog"
        )


async def test_tool_runs_notification_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.modals.notification_modal import NotificationModal
    from sase.notifications.models import Notification

    _pin_tool_run_clocks(monkeypatch)
    patch_startup_loaders(monkeypatch, agents=[])
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_options.format_relative_time",
        lambda _timestamp: "4m ago",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_sent_at.format_relative_time",
        lambda _timestamp: "4m ago",
    )
    run_id = "6c3d5107" + "0" * 24
    modal = NotificationModal(
        [
            Notification(
                id="visual-tool-run-settled",
                timestamp="2026-07-28T12:03:00+00:00",
                sender="tool-run",
                notes=[
                    "Tool run check failed (exit 1)",
                    "cause: failed",
                    f"sase tool show {run_id}",
                ],
                tags=["tool-run"],
                action="OpenToolRun",
                action_data={
                    "run_id": run_id,
                    "command": f"sase tool show {run_id}",
                },
            )
        ]
    )

    async with AcePage(query='"visual"', size=(120, 40), patches=patches()) as page:
        await wait_for_startup(page)
        page.app.push_screen(modal)
        await page.expect_modal("NotificationModal")
        await wait_for_svg_contains(page, "⚒")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "tool_runs_notification_120x40",
            title="ACE tool run settlement notification",
        )


async def test_tool_runs_procs_marker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.proc_observer import ObservedProc
    from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
        _FIXED_TASK_NOW,
        _freeze_procs_clock,
        _open_procs_modal,
        _seed_tasks_tab_queue,
    )

    _pin_tool_run_clocks(monkeypatch)
    patch_startup_loaders(monkeypatch)
    _freeze_procs_clock(monkeypatch)
    run_id = "6c3d5107" + "0" * 24

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        _seed_tasks_tab_queue(
            page.app,
            extra_rows=(
                ObservedProc(
                    proc_id="handoff-check",
                    proc_type="tool",
                    cl_name="",
                    project_file="",
                    status="running",
                    message="sase tool run check",
                    started_at=_FIXED_TASK_NOW.replace(tzinfo=None),
                    display_name="tool:check",
                    output="",
                    command=["sase", "tool", "run", "check"],
                    tags=["tool-run", f"tool-run:{run_id}"],
                ),
            ),
        )
        await _open_procs_modal(page)
        await page.press("end")
        await wait_for_svg_contains(page, "tool:check")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page, "tool_runs_procs_marker_120x40", title="ACE tool run procs marker"
        )
