"""Deterministic startup patches for ACE PNG visual snapshot tests."""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.actions.axe_display._data import AxeCollectedData
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.memory.read_log import MemoryReadEvent
from sase.skills.use_log import SkillUseEvent


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
            # The indicator renders one chip per tab, so the fixture spends its
            # 19 unread rows across two tabs rather than one opaque total.
            tabs=[
                SimpleNamespace(
                    key="hitl",
                    kind="hitl",
                    count=1,
                    oldest_activity_at=None,
                    next_wake_at=None,
                    color=None,
                ),
                SimpleNamespace(
                    key="general",
                    kind="general",
                    count=18,
                    oldest_activity_at=None,
                    next_wake_at=None,
                    color=None,
                ),
            ],
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
            and not page.app._agent_detail_debouncer.is_pending
        )
    )
