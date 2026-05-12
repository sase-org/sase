"""Shared fixtures for the ACE PNG visual snapshot tests.

The underscore prefix keeps pytest from collecting this module.
"""

from __future__ import annotations

from datetime import datetime
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
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.axe.state import LumberjackMetrics, LumberjackStatus


def changespecs() -> list[Any]:
    return [
        make_changespec(
            name="visual_auth",
            description="Adds deterministic login review coverage.",
            status="Ready",
            cl=None,
            parent="root_plan",
            file_path="/tmp/visual_project.gp",
        ),
        make_changespec(
            name="visual_billing",
            description="Exercises the selected row visual state.",
            status="Draft",
            cl=None,
            parent="visual_auth",
            file_path="/tmp/visual_project.gp",
        ),
        make_changespec(
            name="visual_cli",
            description="Keeps the list tall enough for stable layout.",
            status="WIP",
            cl=None,
            parent=None,
            file_path="/tmp/visual_project.gp",
        ),
    ]


def agents() -> list[Agent]:
    started = datetime(2026, 5, 9, 10, 0, 0)
    stopped = datetime(2026, 5, 9, 10, 7, 30)
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan",
            project_file="/workspace/sase/visual_project.gp",
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
            project_file="/workspace/sase/visual_project.gp",
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
            project_file="/workspace/sase/visual_project.gp",
            status="PLAN DONE",
            start_time=datetime(2026, 5, 9, 10, 10, 0),
            stop_time=datetime(2026, 5, 9, 10, 12, 0),
            raw_suffix="20260509-101000-review",
            agent_name="reviewer",
            tag="visual",
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
    axe_data: AxeCollectedData | None = None,
) -> None:
    """Replace background startup data sources with deterministic fixtures."""
    import sase.notifications as notifications
    from sase.ace import grouping_strategy
    from sase.ace.tui.actions.agents import _loading
    from sase.ace.tui.models.agent_groups import GroupingMode
    from sase.ace.tui.models.changespec_groups import ChangeSpecGroupingMode
    from sase.ace.tui.widgets import llm_override_indicator
    from sase.llm_provider import temporary_override

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

    monkeypatch.setattr(_loading, "load_agents_from_disk_with_state", _fake_load_agents)
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

    assert (
        llm_override_indicator.resolve_effective_default_provider_model
        is _fake_resolve_effective_default_provider_model
    ), "LLM provider resolver patch did not bind — visual snapshot may re-leak state"


async def wait_for_startup(page: AcePage) -> None:
    await page.wait_for(
        lambda _state: (
            page.app._agents_first_load_done and page.app._axe_first_load_done
        )
    )
