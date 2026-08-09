"""Agents-tab search must not promote normal loads to full history."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.actions.agents._loading_helpers import _AgentDiskLoadResult
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_content_search import AgentContentSearchCache
from sase.ace.tui.models.agent_loader import AgentLoadState


def _load_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier1",
        complete_visible_inbox=True,
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )


class _SearchLoadApp(AgentLoadingMixin):
    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.hide_non_run_agents = False
        self._agents = []
        self._agents_with_children = []
        self._agents_last_identity = None
        self._agent_search_query = "status:failed"
        self._agent_content_search_cache = AgentContentSearchCache()
        self._agent_content_search_index = None
        self._agents_seen_complete_history = False
        self._agent_load_state = None
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agents_disk_signature: tuple[int, int] | None = None
        self._dismissed_agents_disk_identities: set[
            tuple[AgentType, str, str | None]
        ] = set()
        self._dismissed_agents_disk_signature_initialized = True
        self.applied = False
        self.applied_kwargs: dict[str, Any] | None = None

    def _apply_loaded_agents(self, *_args: object, **_kwargs: object) -> None:
        self.applied = True

    def _apply_loaded_agents_prepared(self, *args: object, **kwargs: object) -> None:
        self.applied = True
        self.applied_kwargs = kwargs


def test_sync_agents_search_load_stays_visible_inbox() -> None:
    app = _SearchLoadApp()
    calls: list[bool] = []

    def fake_load_agents(*_args: object, **kwargs: object) -> _AgentDiskLoadResult:
        calls.append(bool(kwargs.get("full_history")))
        return _AgentDiskLoadResult(
            all_agents=[],
            dismissed_from_loader=[],
            load_state=_load_state(),
        )

    with (
        patch.object(app, "_merge_external_dismissals"),
        patch("sase.ace.patch.find_all_patches_cached", return_value=[]),
        patch(
            "sase.ace.tui.actions.agents._loading.load_agents_from_disk_with_state",
            side_effect=fake_load_agents,
        ),
        patch("sase.ace.tui.repro.capture.record_agents_tab_loader_result"),
    ):
        app._load_agents()

    assert calls == [False]
    assert app.applied is True


async def test_async_agents_search_load_stays_visible_inbox() -> None:
    app = _SearchLoadApp()
    calls: list[bool] = []

    def fake_load_agents(*_args: object, **kwargs: object) -> _AgentDiskLoadResult:
        calls.append(bool(kwargs.get("full_history")))
        return _AgentDiskLoadResult(
            all_agents=[],
            dismissed_from_loader=[],
            load_state=_load_state(),
        )

    with (
        patch(
            "sase.ace.tui.actions.agents._loading_disk."
            "_compute_external_dismissal_merge",
            return_value=None,
        ),
        patch("sase.ace.patch.find_all_patches_cached", return_value=[]),
        patch(
            "sase.ace.tui.actions.agents._loading.load_agents_from_disk_with_state",
            side_effect=fake_load_agents,
        ),
        patch("sase.ace.tui.repro.capture.record_agents_tab_loader_result"),
    ):
        await app._load_agents_async()

    assert calls == [False]
    assert app.applied is True
