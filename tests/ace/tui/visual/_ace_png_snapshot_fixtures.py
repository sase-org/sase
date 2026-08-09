"""Deterministic data builders for ACE PNG visual snapshot tests.

The underscore prefix keeps pytest from collecting this module.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sase.ace.testing import make_patch
from sase.ace.tui.actions.axe_display._data import (
    AxeCollectedData,
    BgCmdSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.ace.tui.models.agent import Agent, AgentType, AttemptRecord
from sase.axe.state import LumberjackMetrics, LumberjackStatus
from sase.core.project_lifecycle_wire import ProjectRecordWire


def patches() -> list[Any]:
    return [
        make_patch(
            name="visual_auth",
            description="Adds deterministic login review coverage.",
            status="Ready",
            cl=None,
            parent="root_plan",
            file_path="/tmp/visual_project.sase",
        ),
        make_patch(
            name="visual_billing",
            description="Exercises the selected row visual state.",
            status="Draft",
            cl=None,
            parent="visual_auth",
            file_path="/tmp/visual_project.sase",
        ),
        make_patch(
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
            tribe="visual",
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
            tribe="visual",
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
            tribe="review",
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
            tribe="verification",
            error_message="fixture failure for modal row styling",
        ),
    ]


def hood_neighbor_agents() -> list[Agent]:
    """Agents spanning the ``visual.code`` and ``visual`` hood groups.

    Agent 1 keeps a long single suffix segment to exercise modal-row truncation.
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
            tribe="review",
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
            tribe="verification",
            error_message="fixture failure for modal row styling",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-cousin-review-with-extra-context",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 23, 13, 18, 0),
            stop_time=datetime(2026, 5, 23, 13, 20, 15),
            raw_suffix="20260523-131800-cousin",
            agent_name="visual.review.cousin",
            tribe="review",
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
