"""Shared helpers for agent revive tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._revive import AgentRevivalMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import panel_key_per_agent


def make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for revive tests."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.WORKFLOW,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "DONE",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "workflow": "wf",
        "raw_suffix": "20240101120000",
        "artifacts_dir": "/tmp/projects/myproj/artifacts/workflow-wf/20240101120000",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class FakeReviveApp(AgentRevivalMixin):
    """Minimal app with only the revive dependencies."""

    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.current_attempt_number: int | None = None
        self._current_group_key: tuple[str, ...] | None = None
        self._agent_panels_grouped = False
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._dismiss_revive_epoch = 0
        self._revived_agent_raw_suffixes: set[str] = set()
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self.loaded_agents: list[Agent] | None = None
        self.notifications: list[tuple[str, str]] = []
        self.restored: list[tuple[tuple[AgentType, str, str | None], str | None]] = []
        self.load_count = 0
        self.refresh_count = 0
        self.refresh_calls: list[bool] = []
        self.delta_refresh_count = 0
        self.delta_refreshes: list[tuple[list[str], str]] = []
        self.refilter_count = 0

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _load_agents(self, *, full_history: bool = False) -> None:
        self.load_count += 1
        self.last_load_full_history = full_history
        if self.loaded_agents is not None:
            self._agents = self.loaded_agents

    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        del prior_pos
        self.refilter_count += 1

    def _bump_dismiss_revive_epoch(self) -> None:
        self._dismiss_revive_epoch += 1

    def _schedule_agents_async_refresh(
        self,
        *,
        source: str = "unknown",
        full_history: bool = False,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        del source
        # Simulate the async load completing synchronously so existing test
        # assertions about post-load selection / refresh counts still hold.
        self._load_agents(full_history=full_history)
        if on_complete is not None:
            on_complete()

    def _schedule_agent_artifact_delta_refresh(
        self,
        artifact_dirs: list[Path],
        *,
        source: str = "unknown",
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        self.delta_refresh_count += 1
        self.delta_refreshes.append(([str(path) for path in artifact_dirs], source))
        self._load_agents(full_history=False)
        if on_complete is not None:
            on_complete()

    def _refresh_agents_display(self, *, list_changed: bool) -> None:
        self.refresh_calls.append(list_changed)
        if list_changed:
            self.refresh_count += 1

    def _panel_keys_per_agent(self) -> list[str | None]:
        return panel_key_per_agent(
            self._agents,
            merge_tribe_panels=getattr(self, "_agent_panels_grouped", False),
        )

    def _restore_agent_artifacts(
        self,
        agent: Agent,
        *,
        parent_artifacts_dir: str | None = None,
    ) -> None:
        self.restored.append((agent.identity, parent_artifacts_dir))


class RealArtifactReviveApp(FakeReviveApp):
    """Revive fake that uses the real artifact restoration helpers."""

    _restore_agent_artifacts = AgentRevivalMixin._restore_agent_artifacts


def patch_home(tmp_path: Path) -> patch:  # type: ignore[type-arg]
    """Point ``Path.home()`` at *tmp_path* for the duration of a test."""

    def _path_home() -> Path:
        return tmp_path

    return patch.object(Path, "home", _path_home)
