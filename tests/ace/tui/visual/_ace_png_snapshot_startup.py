"""Deterministic startup patches for ACE PNG visual snapshot tests."""

from __future__ import annotations

from collections.abc import Sequence
from importlib.resources import files as importlib_files
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.actions.axe_display._data import AxeCollectedData
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.widgets.notification_indicator import NotificationIndicator
from sase.config.loading import load_default_config
from sase.memory.read_log import MemoryReadEvent
from sase.skills.use_log import SkillUseEvent

# Default visual-suite inbox: one Gates chip and one General chip. Goldens of
# unrelated surfaces still show this badge, so startup waits for the exact
# plain text rather than whatever the isolated SASE_HOME store last held.
DEFAULT_VISUAL_NOTIFICATION_BADGE = " ⚑1 ✉18 "

_VISUAL_NOTIFICATION_BADGE: str | None = None


def _default_visual_notification_snapshot() -> SimpleNamespace:
    """Return the deterministic two-tab inbox every visual page starts from."""
    return SimpleNamespace(
        notifications=[],
        expired_ids=[],
        counts=SimpleNamespace(priority=1, rest=18, muted=0, errors=0),
        tabs=[
            SimpleNamespace(
                key="hitl",
                kind="hitl",
                count=1,
                oldest_activity_at=None,
                next_wake_at=None,
                color=None,
                icon=None,
            ),
            SimpleNamespace(
                key="general",
                kind="general",
                count=18,
                oldest_activity_at=None,
                next_wake_at=None,
                color=None,
                icon=None,
            ),
        ],
    )


def _indicator_plain(page: AcePage) -> str | None:
    """Return the top-bar badge text, or ``None`` when it is not mounted."""
    try:
        indicator = page.app.query_one("#notification-indicator", NotificationIndicator)
    except Exception:
        return None
    return indicator.render().plain


def _shipped_ace_config() -> dict[str, Any]:
    """Load packaged defaults so host ``notification_tabs`` cannot restyle chips."""
    return load_default_config(importlib_files)


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
    from sase.ace.tui.models.patch_groups import PatchGroupingMode
    from sase.ace.tui.widgets import llm_override_indicator, notification_tab_style
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

    def _fake_prompt_catalog_rebuild(
        app: AceApp,
        *,
        reason: str,
        force: bool = False,
        config_dirty: bool = False,
    ) -> None:
        """Disable prompt-catalog I/O; visual tests inject prompt rows directly."""
        del reason, force, config_dirty
        app._prompt_catalog_rebuild_in_flight = False
        app._prompt_catalog_rebuild_pending = False
        app._prompt_catalog_rebuild_pending_force = False
        app._prompt_catalog_rebuild_pending_config_dirty = False

    def _fake_notification_snapshot(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return _default_visual_notification_snapshot()

    def _fake_load_agent_grouping_mode(*_args: Any, **_kwargs: Any) -> GroupingMode:
        return GroupingMode.STANDARD

    def _fake_load_patch_grouping_mode(
        *_args: Any, **_kwargs: Any
    ) -> PatchGroupingMode:
        return PatchGroupingMode.BY_PROJECT

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
        AceApp,
        "_schedule_prompt_catalog_rebuild",
        _fake_prompt_catalog_rebuild,
    )
    monkeypatch.setattr(
        notifications,
        "read_notification_snapshot",
        _fake_notification_snapshot,
    )
    monkeypatch.setattr(
        notification_tab_style,
        "load_merged_config",
        _shipped_ace_config,
    )
    notification_tab_style._configured_tab_styles_for_token.cache_clear()
    notification_tab_style._indicator_max_counts_for_token.cache_clear()
    monkeypatch.setattr(
        f"{__name__}._VISUAL_NOTIFICATION_BADGE",
        DEFAULT_VISUAL_NOTIFICATION_BADGE,
    )
    monkeypatch.setattr(
        grouping_strategy,
        "load_agent_grouping_mode",
        _fake_load_agent_grouping_mode,
    )
    monkeypatch.setattr(
        grouping_strategy,
        "load_patch_grouping_mode",
        _fake_load_patch_grouping_mode,
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
    expected_badge = _VISUAL_NOTIFICATION_BADGE
    await page.wait_for(
        lambda _state: (
            page.app._patches_first_load_done
            and page.app._agents_first_load_done
            and page.app._axe_first_load_done
            and not page.app._agent_detail_debouncer.is_pending
            and (expected_badge is None or _indicator_plain(page) == expected_badge)
        )
    )
