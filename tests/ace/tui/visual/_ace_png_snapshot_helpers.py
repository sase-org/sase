"""Shared fixtures for the ACE PNG visual snapshot tests.

The underscore prefix keeps pytest from collecting this module.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime
import hashlib
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage, make_changespec
from sase.ace.tui import AceApp
from sase.ace.tui.actions.axe_display._data import (
    AxeCollectedData,
    BgCmdSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.ace.tui.models.agent import Agent, AgentType, AttemptRecord
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.axe.state import LumberjackMetrics, LumberjackStatus
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.memory.read_log import MemoryReadEvent
from sase.skills.use_log import SkillUseEvent


def changespecs() -> list[Any]:
    return [
        make_changespec(
            name="visual_auth",
            description="Adds deterministic login review coverage.",
            status="Ready",
            cl=None,
            parent="root_plan",
            file_path="/tmp/visual_project.sase",
        ),
        make_changespec(
            name="visual_billing",
            description="Exercises the selected row visual state.",
            status="Draft",
            cl=None,
            parent="visual_auth",
            file_path="/tmp/visual_project.sase",
        ),
        make_changespec(
            name="visual_cli",
            description="Keeps the list tall enough for stable layout.",
            status="WIP",
            cl=None,
            parent=None,
            file_path="/tmp/visual_project.sase",
        ),
    ]


def agents() -> list[Agent]:
    started = datetime(2026, 5, 9, 10, 0, 0)
    stopped = datetime(2026, 5, 9, 10, 7, 30)
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=started,
            stop_time=stopped,
            raw_suffix="20260509-100000-plan",
            agent_name="planner",
            llm_provider="codex",
            model="gpt-5",
            response_path="/workspace/sase/artifacts/visual-plan/response.md",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-code",
            project_file="/workspace/sase/visual_project.sase",
            status="FAILED",
            start_time=datetime(2026, 5, 9, 10, 8, 0),
            stop_time=datetime(2026, 5, 9, 10, 9, 5),
            raw_suffix="20260509-100800-code",
            agent_name="coder",
            error_message="focused fixture failure",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-review",
            project_file="/workspace/sase/visual_project.sase",
            status="PLAN DONE",
            start_time=datetime(2026, 5, 9, 10, 10, 0),
            stop_time=datetime(2026, 5, 9, 10, 12, 0),
            raw_suffix="20260509-101000-review",
            agent_name="reviewer",
            tag="visual",
        ),
    ]


def retry_agent(
    *,
    name: str,
    status: str,
    start_time: datetime,
    raw_suffix: str,
    stop_time: datetime | None = None,
    retry_status: str | None = None,
    retry_count: int = 0,
    max_retries: int = 0,
    retry_next_at_epoch: float | None = None,
    retry_attempt: int = 0,
    retry_of_timestamp: str | None = None,
    retry_chain_root_timestamp: str | None = None,
    retried_as_timestamp: str | None = None,
    retry_terminal: bool = False,
    using_fallback: bool = False,
    fallback_model: str | None = None,
    attempt_history: Sequence[AttemptRecord] = (),
) -> Agent:
    """Build a deterministic Agents-tab fixture with retry metadata."""
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"visual-{name}",
        project_file="/workspace/sase/visual_project.sase",
        status=status,
        start_time=start_time,
        stop_time=stop_time,
        raw_suffix=raw_suffix,
        agent_name=f"retry-{name}",
        llm_provider="codex",
        model="gpt-5",
        retry_status=retry_status,
        retry_count=retry_count,
        max_retries=max_retries,
        retry_next_at_epoch=retry_next_at_epoch,
        retry_attempt=retry_attempt,
        retry_of_timestamp=retry_of_timestamp,
        retry_chain_root_timestamp=retry_chain_root_timestamp,
        retried_as_timestamp=retried_as_timestamp,
        retry_terminal=retry_terminal,
        using_fallback=using_fallback,
        fallback_model=fallback_model,
        attempt_history=list(attempt_history),
    )


def agents_with_stopped_status() -> list[Agent]:
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 0, 0),
            stop_time=datetime(2026, 5, 9, 10, 7, 30),
            raw_suffix="20260509-100000-plan",
            agent_name="planner",
            llm_provider="codex",
            model="gpt-5",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-code",
            project_file="/workspace/sase/visual_project.sase",
            status="FAILED",
            start_time=datetime(2026, 5, 9, 10, 8, 0),
            stop_time=datetime(2026, 5, 9, 10, 9, 5),
            raw_suffix="20260509-100800-code",
            agent_name="coder",
            error_message="focused fixture failure",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-repeat-slot",
            project_file="/workspace/sase/visual_project.sase",
            status="STOPPED",
            start_time=datetime(2026, 5, 9, 10, 9, 30),
            stop_time=datetime(2026, 5, 9, 10, 9, 30),
            raw_suffix="20260509-100930-stopped",
            agent_name="repeat.slot",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-review",
            project_file="/workspace/sase/visual_project.sase",
            status="PLAN DONE",
            start_time=datetime(2026, 5, 9, 10, 10, 0),
            stop_time=datetime(2026, 5, 9, 10, 12, 0),
            raw_suffix="20260509-101000-review",
            agent_name="reviewer",
            tag="visual",
        ),
    ]


def project_records() -> list[ProjectRecordWire]:
    """Deterministic project lifecycle records for the management modal.

    A spread across states, claim counts, launchability, warnings, explicit vs
    defaulted state, and name/path lengths so the full-screen layout, column
    alignment, state badges, and warning styling are all exercised.
    """

    def _record(
        name: str,
        *,
        state: str,
        explicit: bool = True,
        claims: int = 0,
        launchable: bool = True,
        warnings: list[str] | None = None,
        aliases: list[str] | None = None,
        workspace_dir: str | None = None,
        display_name: str | None = None,
        is_project: bool = True,
        vcs_kind: str | None = "gh",
    ) -> ProjectRecordWire:
        project_dir = f"/home/visual/.sase/projects/{name}"
        return ProjectRecordWire(
            schema_version=1,
            project_name=name,
            project_dir=project_dir,
            project_file=f"{project_dir}/{name}.sase",
            archive_file=None,
            workspace_dir=(
                workspace_dir
                if workspace_dir is not None
                else f"/home/visual/work/{name}"
            ),
            state=state,
            state_explicit=explicit,
            system_managed=False,
            active_claim_count=claims,
            launchable=launchable,
            aliases=aliases or [],
            warnings=warnings or [],
            parse_warnings=[],
            display_name=display_name,
            is_project=is_project,
            vcs_kind=vcs_kind,
        )

    return [
        _record("sase", state="enabled", claims=2, aliases=["bob"]),
        _record("sase-core", state="enabled", claims=1, explicit=False),
        _record(
            "project-management-fullscreen",
            state="enabled",
            claims=0,
            workspace_dir="/home/visual/work/project-management-fullscreen",
        ),
        _record(
            "old-experiment",
            state="disabled",
            launchable=False,
            warnings=["workspace checkout is missing"],
            vcs_kind="git",
        ),
        _record(
            "sase-core-sibling",
            state="sibling",
            launchable=False,
            is_project=False,
            vcs_kind=None,
        ),
        _record("scratch-spike", state="disabled", launchable=False),
        _record(
            "old-prototype",
            state="disabled",
            launchable=False,
            warnings=["spec parse error", "orphaned lock"],
        ),
    ]


def visual_agents() -> list[Agent]:
    started = datetime(2026, 5, 23, 13, 0, 0)
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan-review-with-a-long-display-name",
            project_file="/workspace/sase/visual_project.sase",
            status="RUNNING",
            start_time=started,
            raw_suffix="20260523-130000-plan",
            agent_name="visual.plan.review.contract.snapshot",
            llm_provider="codex",
            model="gpt-5",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-code-implementation-with-extra-context",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 23, 13, 8, 0),
            stop_time=datetime(2026, 5, 23, 13, 12, 30),
            raw_suffix="20260523-130800-code",
            agent_name="visual.code.implementation.with.narrow.row",
            tag="review",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-verification-pass-with-extra-context",
            project_file="/workspace/sase/visual_project.sase",
            status="FAILED",
            start_time=datetime(2026, 5, 23, 13, 16, 0),
            stop_time=datetime(2026, 5, 23, 13, 17, 5),
            raw_suffix="20260523-131600-verify",
            agent_name="visual.verify.performance.and.polish",
            tag="verification",
            error_message="fixture failure for modal row styling",
        ),
    ]


def hood_neighbor_agents() -> list[Agent]:
    """Three agents that all share the ``visual.code`` hood, so they are
    neighbors under the dotted-name hood model. Agent 1 keeps a long single
    suffix segment to exercise modal-row truncation.
    """
    started = datetime(2026, 5, 23, 13, 0, 0)
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan-review-with-a-long-display-name",
            project_file="/workspace/sase/visual_project.sase",
            status="RUNNING",
            start_time=started,
            raw_suffix="20260523-130000-plan",
            agent_name="visual.code.plan",
            llm_provider="codex",
            model="gpt-5",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-code-implementation-with-extra-context",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 23, 13, 8, 0),
            stop_time=datetime(2026, 5, 23, 13, 12, 30),
            raw_suffix="20260523-130800-code",
            agent_name="visual.code.implementationwithanextremelylongsuffix",
            tag="review",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-verification-pass-with-extra-context",
            project_file="/workspace/sase/visual_project.sase",
            status="FAILED",
            start_time=datetime(2026, 5, 23, 13, 16, 0),
            stop_time=datetime(2026, 5, 23, 13, 17, 5),
            raw_suffix="20260523-131600-verify",
            agent_name="visual.code.verify",
            tag="verification",
            error_message="fixture failure for modal row styling",
        ),
    ]


def axe_collected_data(
    *,
    bgcmd_slots: list[tuple[int, Any]] | None = None,
    bgcmd_details: dict[int, BgCmdSnapshot] | None = None,
    lumberjack_names: list[str] | None = None,
    lumberjack_statuses: dict[str, LumberjackStatus | None] | None = None,
    lumberjack_metrics: dict[str, LumberjackMetrics | None] | None = None,
    lumberjack_log_tails: dict[str, str] | None = None,
    lumberjack_chop_names: dict[str, list[str]] | None = None,
    chop_snapshots: dict[tuple[str, str], ChopSnapshot] | None = None,
    lumberjack_snapshots: dict[str, LumberjackSnapshot] | None = None,
) -> AxeCollectedData:
    """Build a deterministic AxeCollectedData fixture for the Axe tab."""
    return AxeCollectedData(
        axe_running=False,
        axe_status=None,
        axe_metrics=None,
        axe_output="",
        lumberjack_names=list(lumberjack_names or []),
        bgcmd_slots=list(bgcmd_slots or []),
        lumberjack_statuses=dict(lumberjack_statuses or {}),
        lumberjack_metrics=dict(lumberjack_metrics or {}),
        lumberjack_log_tails=dict(lumberjack_log_tails or {}),
        bgcmd_details=dict(bgcmd_details or {}),
        lumberjack_chop_names=dict(lumberjack_chop_names or {}),
        chop_snapshots=dict(chop_snapshots or {}),
        lumberjack_snapshots=dict(lumberjack_snapshots or {}),
    )


def patch_startup_loaders(
    monkeypatch: pytest.MonkeyPatch,
    *,
    agents: list[Agent] | None = None,
    use_real_agent_loader: bool = False,
    axe_data: AxeCollectedData | None = None,
    memory_reads: Sequence[MemoryReadEvent] | None = None,
    skill_uses: Sequence[SkillUseEvent] | None = None,
    opened_workspaces: Sequence[OpenedWorkspaceDisplayEvent] | None = None,
) -> None:
    """Replace background startup data sources with deterministic fixtures."""
    import sase.notifications as notifications
    from sase.ace import grouping_strategy
    from sase.ace.tui import memory_reads as memory_reads_module
    from sase.ace.tui import opened_workspaces as opened_workspaces_module
    from sase.ace.tui import skill_uses as skill_uses_module
    from sase.ace.tui.actions import update_toast
    from sase.ace.tui.actions.agents import _loading
    from sase.ace.tui.models.agent_groups import GroupingMode
    from sase.ace.tui.models.changespec_groups import ChangeSpecGroupingMode
    from sase.ace.tui.widgets import llm_override_indicator
    from sase.llm_provider import temporary_override
    from sase.updates import IncomingCommits

    state = AgentLoadState(
        tier="tier2",
        complete_history=True,
        artifact_source="source_scan",
        used_artifact_index=False,
    )

    def _fake_load_agents(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            all_agents=list(agents or []),
            dismissed_from_loader=[],
            load_state=state,
        )

    memory_read_events = tuple(memory_reads or ())
    skill_use_events = tuple(skill_uses or ())
    opened_workspace_events = tuple(opened_workspaces or ())

    def _fake_load_memory_reads_for_agent(
        *_args: Any, limit: int = len(memory_read_events), **_kwargs: Any
    ) -> tuple[MemoryReadEvent, ...]:
        return memory_read_events[:limit]

    def _fake_load_skill_uses_for_agent(
        *_args: Any, limit: int = len(skill_use_events), **_kwargs: Any
    ) -> tuple[SkillUseEvent, ...]:
        return skill_use_events[:limit]

    def _fake_load_opened_workspaces_for_agent(
        *_args: Any, limit: int = len(opened_workspace_events), **_kwargs: Any
    ) -> tuple[OpenedWorkspaceDisplayEvent, ...]:
        return opened_workspace_events[:limit]

    async def _fake_axe_startup(app: AceApp) -> None:
        if axe_data is not None:
            app._apply_axe_status_data(axe_data)
        else:
            app._axe_first_load_done = True
            app._maybe_end_startup_stopwatch()

    async def _fake_axe_status_async(app: AceApp) -> None:
        if axe_data is not None:
            app._apply_axe_status_data(axe_data)
        else:
            app._axe_first_load_done = True

    def _fake_notification_snapshot(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            notifications=[],
            expired_ids=[],
            counts=SimpleNamespace(priority=1, rest=18, muted=0, errors=0),
        )

    def _fake_load_agent_grouping_mode(*_args: Any, **_kwargs: Any) -> GroupingMode:
        return GroupingMode.STANDARD

    def _fake_load_changespec_grouping_mode(
        *_args: Any, **_kwargs: Any
    ) -> ChangeSpecGroupingMode:
        return ChangeSpecGroupingMode.BY_PROJECT

    def _fake_resolve_effective_default_provider_model(
        *_args: Any, **_kwargs: Any
    ) -> tuple[str, str]:
        return ("codex", "visual-snapshot-model")

    def _fake_get_active_temporary_override(*_args: Any, **_kwargs: Any) -> None:
        return None

    if not use_real_agent_loader:
        monkeypatch.setattr(
            _loading, "load_agents_from_disk_with_state", _fake_load_agents
        )
    monkeypatch.setattr(
        memory_reads_module,
        "_load_memory_reads_for_agent",
        _fake_load_memory_reads_for_agent,
    )
    monkeypatch.setattr(
        skill_uses_module,
        "_load_skill_uses_for_agent",
        _fake_load_skill_uses_for_agent,
    )
    monkeypatch.setattr(
        opened_workspaces_module,
        "_load_opened_workspaces_for_agent",
        _fake_load_opened_workspaces_for_agent,
    )
    monkeypatch.setattr(AceApp, "_run_axe_startup_init", _fake_axe_startup)
    monkeypatch.setattr(AceApp, "_load_axe_status_async", _fake_axe_status_async)
    monkeypatch.setattr(
        notifications,
        "read_notification_snapshot",
        _fake_notification_snapshot,
    )
    monkeypatch.setattr(
        grouping_strategy,
        "load_agent_grouping_mode",
        _fake_load_agent_grouping_mode,
    )
    monkeypatch.setattr(
        grouping_strategy,
        "load_changespec_grouping_mode",
        _fake_load_changespec_grouping_mode,
    )
    monkeypatch.setattr(
        temporary_override,
        "resolve_effective_default_provider_model",
        _fake_resolve_effective_default_provider_model,
    )
    monkeypatch.setattr(
        temporary_override,
        "get_active_temporary_override",
        _fake_get_active_temporary_override,
    )
    monkeypatch.setattr(
        llm_override_indicator,
        "resolve_effective_default_provider_model",
        _fake_resolve_effective_default_provider_model,
    )
    monkeypatch.setattr(
        llm_override_indicator,
        "get_active_temporary_override",
        _fake_get_active_temporary_override,
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        update_toast,
        "_fetch_incoming_commits",
        lambda *_args, **_kwargs: IncomingCommits(
            total=0,
            commits=(),
            source="unavailable",
            error="visual snapshot stub",
        ),
    )

    assert (
        llm_override_indicator.resolve_effective_default_provider_model
        is _fake_resolve_effective_default_provider_model
    ), "LLM provider resolver patch did not bind — visual snapshot may re-leak state"


async def wait_for_startup(page: AcePage) -> None:
    await page.wait_for(
        lambda _state: (
            page.app._changespecs_first_load_done
            and page.app._agents_first_load_done
            and page.app._axe_first_load_done
        )
    )


_VISUAL_DEBOUNCERS = (
    "_changespec_detail_debouncer",
    "_agent_detail_debouncer",
    "_axe_detail_debouncer",
)
_VISUAL_STABLE_FRAME_COUNT = 3
# Short one-shot timers cover input diagnostics, validation, and pressed-state
# cleanup. Longer one-shots (for example toast expiry) intentionally keep a
# stable visible surface alive and must not be awaited until it disappears.
_VISUAL_SETTLING_TIMER_MAX_SECONDS = 0.5


def _clear_transient_button_state(page: AcePage) -> None:
    from textual.widgets import Button

    # Button.press() adds a transient pressed highlight and removes it on a
    # timer; visual snapshots should capture the resting state, not race that
    # timer.
    for screen in page.app.screen_stack:
        for button in screen.query(Button):
            button.remove_class("-active")


def _pending_visual_work(page: AcePage) -> tuple[list[str], list[str], list[str]]:
    """Describe finite work that can still change an ACE screenshot."""
    debouncers = [
        name
        for name in _VISUAL_DEBOUNCERS
        if bool(getattr(getattr(page.app, name, None), "is_pending", False))
    ]
    workers = [
        str(getattr(worker, "name", None) or getattr(worker, "description", worker))
        for worker in page.app.workers
        if bool(getattr(worker, "is_running", False))
    ]

    # Textual does not expose a public timer registry. In this test helper it
    # is safe to inspect the message pumps' weak timer sets. Wait for one-shot
    # timers only; recurring clocks are expected to remain alive while the app
    # is mounted and render convergence handles whether they affect the frame.
    nodes: list[Any] = [page.app]
    for screen in page.app.screen_stack:
        nodes.extend(screen.walk_children(with_self=True))
    timers: list[str] = []
    seen_nodes: set[int] = set()
    for node in nodes:
        if id(node) in seen_nodes:
            continue
        seen_nodes.add(id(node))
        for timer in getattr(node, "_timers", ()):
            task = getattr(timer, "_task", None)
            if (
                getattr(timer, "_repeat", None) == 0
                and float(getattr(timer, "_interval", float("inf")))
                <= _VISUAL_SETTLING_TIMER_MAX_SECONDS
                and task is not None
                and not task.done()
            ):
                timers.append(str(getattr(timer, "name", timer)))
    return debouncers, workers, timers


async def wait_for_visual_idle(page: AcePage, *, timeout: float = 2.0) -> None:
    """Wait for finite work to finish and the rendered SVG frame to converge."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    previous_svg: str | None = None
    stable_frames = 0
    frame_digests: list[str] = []
    pending: tuple[list[str], list[str], list[str]] = ([], [], [])

    while True:
        await page.pause()
        _clear_transient_button_state(page)
        pending = _pending_visual_work(page)

        if any(pending):
            previous_svg = None
            stable_frames = 0
        else:
            # Exporting forces Textual to materialize the compositor's current
            # frame. Requiring the same result across separate idle/layout
            # cycles prevents a partially painted frame from reaching the PNG
            # comparator merely because a fixed number of pauses elapsed.
            svg = page.export_svg(title="ACE visual convergence probe")
            digest = hashlib.sha256(svg.encode()).hexdigest()[:12]
            frame_digests.append(digest)
            frame_digests = frame_digests[-4:]
            stable_frames = stable_frames + 1 if svg == previous_svg else 1
            previous_svg = svg
            if stable_frames >= _VISUAL_STABLE_FRAME_COUNT:
                return

        if loop.time() >= deadline:
            debouncers, workers, timers = pending
            raise AssertionError(
                "Timed out waiting for ACE visual render convergence "
                f"after {timeout:.2f}s; stable_frames={stable_frames}/"
                f"{_VISUAL_STABLE_FRAME_COUNT}; frame_digests={frame_digests}; "
                f"pending_debouncers={debouncers}; pending_workers={workers}; "
                f"pending_one_shot_timers={timers}"
            )

        # ``Pilot.pause`` yields until the current queue is idle, but finite
        # timers and thread workers need a small amount of wall-clock progress.
        await asyncio.sleep(min(0.01, max(0.0, deadline - loop.time())))
