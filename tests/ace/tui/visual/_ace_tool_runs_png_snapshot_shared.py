"""Shared ToolRun PNG snapshot fixtures and clock pins.

Public helpers for the ``test_ace_png_snapshots_tool_runs*`` split. This
module is private (``_``-prefixed); the helpers are public so each split test
module can import them without importing a ``_``-prefixed name across modules.
"""

from __future__ import annotations

import time as _real_time
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.tool_runs.detail import LoadedToolRunDetail
from sase.ace.tui.tool_runs.snapshot import _build_snapshot
from sase.core.tool_run import ToolRunBrief, ToolRunGlance, ToolRunNodeSummary
from sase.core.tool_run import ToolRunVerdictSummary
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import wait_for_visual_idle

TOOL_RUN_NOW = datetime(2026, 7, 28, 12, 10, tzinfo=UTC)
TOOL_RUN_EPOCH = 1785239400.0
TOOL_RUN_EPOCH_INT = 1785239400


# Row chips read a naive local now. The visual conftest pins TZ=UTC in a
# function-scoped fixture (after module import), so fixture activity stamps
# must use the same naive conversion the app performs, computed lazily at
# fixture-build time rather than at module import.
def local_now_ts() -> float:
    return TOOL_RUN_NOW.replace(tzinfo=None).timestamp()


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return TOOL_RUN_NOW if tz is None else TOOL_RUN_NOW.astimezone(tz)


class FakeTime:
    """Pin wall-clock reads while leaving monotonic clocks alone."""

    @staticmethod
    def time() -> float:
        return TOOL_RUN_EPOCH

    monotonic = staticmethod(_real_time.monotonic)
    perf_counter = staticmethod(_real_time.perf_counter)
    sleep = staticmethod(_real_time.sleep)
    tzname = staticmethod(_real_time.tzname)


def pin_tool_run_clocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every clock the ToolRun surfaces read (no SQLite, no drift)."""
    from sase.ace.tui.models import agent_time as agent_time_module
    from sase.ace.tui.widgets import _agent_list_render_agent_status as row_module
    from sase.ace.tui.tool_runs import header_chip as header_chip_module
    from sase.ace.tui.tool_runs import links_context as links_context_module
    from sase.ace.tui.tool_runs import links_matching as links_matching_module
    from sase.ace.tui.tool_runs import links_suffixes as links_suffixes_module
    from sase.ace.tui.widgets.decks.tool_runs import loader as runs_loader_module
    from sase.ace.tui.widgets.decks.tool_runs import widget as runs_widget_module
    from sase.ace.tui.widgets.decks.tool_runs import (
        widget_live as runs_widget_live_module,
    )
    from sase.ace.tui.widgets.prompt_panel import _agent_display_header

    pin_agents_visual_now(monkeypatch, TOOL_RUN_NOW.replace(tzinfo=None))
    monkeypatch.setattr(_agent_display_header, "DateTime", FixedDateTime)
    from sase.ace.tui.widgets.prompt_panel import _agent_context_common

    monkeypatch.setattr(_agent_context_common, "get_timezone", lambda: ZoneInfo("UTC"))
    naive = TOOL_RUN_NOW.replace(tzinfo=None)
    monkeypatch.setattr(row_module, "local_now", lambda: naive)
    monkeypatch.setattr(agent_time_module, "local_now", lambda: naive)
    for module in (
        header_chip_module,
        links_context_module,
        links_matching_module,
        links_suffixes_module,
        runs_loader_module,
        runs_widget_module,
        runs_widget_live_module,
    ):
        monkeypatch.setattr(module, "time", FakeTime)


def tool_run_verdict(bucket: str, **counts: Any) -> ToolRunVerdictSummary:
    return ToolRunVerdictSummary(
        bucket=bucket,
        new=int(counts.get("new", 0)),
        known=int(counts.get("known", 0)),
        flaky=int(counts.get("flaky", 0)),
        unknown=int(counts.get("unknown", 0)),
        reasons=tuple(counts.get("reasons", ())),
    )


def tool_run_brief(
    run_id: str,
    label: str = "check",
    bucket: str = "pass",
    *,
    state: str = "succeeded",
    created_ts: int = TOOL_RUN_EPOCH_INT - 600,
    settled_ts: int | None = TOOL_RUN_EPOCH_INT - 359,
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
        verdict=tool_run_verdict(bucket, **counts),
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


def tool_run_glance(
    run_id: str,
    *,
    agent: str | None = "tr-live",
    owner_kind: str | None = None,
    owner_id: str | None = None,
    state: str = "running",
    label: str = "check",
    created_ts: int = TOOL_RUN_EPOCH_INT - 133,
    last_activity_ts: int | None = None,
    stages_done: int = 6,
    stages_expected: int | None = 11,
    parent_run_id: str | None = None,
    stop_requested: bool = False,
    typical_ms: int | None = 253000,
) -> ToolRunGlance:
    if last_activity_ts is None:
        last_activity_ts = int(local_now_ts()) - 3
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


def tool_run_summary(
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


def tool_run_agent(name: str, status: str = "RUNNING", **over: Any) -> Agent:
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


def seed_tool_run_surfaces(
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
    from sase.ace.tui.widgets.decks.tool_runs import loader as runs_loader_module

    snap = _build_snapshot(list(glances), generation=3)
    snapshot_module._set_snapshot(snap)
    # The summary/detail layers keep module-global LRUs that outlive one
    # test. Identical fixtures run twice in this split (facade plus split
    # module), so reset both to cold: otherwise the second run takes the
    # synchronous cached paint with an empty detail LRU and renders every
    # block as "run detail unavailable" without ever spawning its worker.
    with summaries_module._summary_lock:
        summaries_module._summary_lru.clear()
    with detail_module._detail_lock:
        detail_module._detail_lru.clear()
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
    monkeypatch.setattr(runs_loader_module, "load_tool_run_detail_blocking", _load)


async def show_runs_card(page: AcePage) -> None:
    page.app.action_show_tool_runs_card()
    await wait_for_visual_idle(page)


async def select_agent(page: AcePage, name: str, *, max_steps: int = 12) -> None:
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
