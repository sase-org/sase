from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._dismissing import AgentDismissingMixin
from sase.ace.tui.models.agent import Agent, AgentType

from tests._agent_cleanup_proc_helpers import TrackedProcRecorderMixin


def make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for dismiss tests."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "DONE",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": "20240101120000",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class FakeDismissApp(TrackedProcRecorderMixin, AgentDismissingMixin):
    """Minimal app implementing just what the dismiss flow touches."""

    def __init__(self) -> None:
        self._init_tracked_task_recorder()
        self.current_tab = "agents"
        self.current_idx = 0
        self.patches = []  # type: ignore[assignment]
        self._agents: list[Agent] = []
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._revived_agent_raw_suffixes: set[str] = set()
        self._agents_with_children: list[Agent] = []
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]] = (
            set()
        )
        self._scheduled: list[tuple[object, tuple[object, ...]]] = []
        self.notifications: list[tuple[str, str]] = []
        self.load_count = 0
        self.refilter_count = 0
        self.notification_refreshes = 0
        self.notification_refreshes_async = 0
        self.async_refreshes = 0

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _load_agents(self) -> None:
        self.load_count += 1

    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        self.refilter_count += 1
        self.last_refilter_prior_pos = prior_pos

    def _refresh_notification_count(self) -> None:
        self.notification_refreshes += 1

    async def _refresh_notification_count_async(self) -> None:
        self.notification_refreshes_async += 1

    def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
        del source
        self.async_refreshes += 1

    def call_later(self, callback: object, *args: object) -> None:
        self._scheduled.append((callback, args))

    def call_after_refresh(self, callback: object, *args: object) -> None:
        # In tests we don't simulate Textual's refresh tick; fire the
        # callback synchronously so notify() side effects land in
        # ``self.notifications`` for assertions.
        callback(*args)  # type: ignore[operator]


def patch_isolated_home(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Point Path.home(), bundles dir, and dismissed.json at *tmp_path*."""

    def _path_home() -> Path:
        return tmp_path

    return [
        patch.object(Path, "home", _path_home),
        patch(
            "sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR",
            tmp_path / "dismissed_bundles",
        ),
        patch(
            "sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE",
            tmp_path / "dismissed_agents.json",
        ),
        patch(
            "sase.ace.dismissed_agents._OLD_BUNDLES_FILE",
            tmp_path / "old_bundles.json",
        ),
    ]
