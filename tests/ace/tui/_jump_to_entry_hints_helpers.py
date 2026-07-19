"""Shared harnesses for jump-to-entry hint tests."""

from typing import Any
from unittest.mock import MagicMock

from textual.app import App, ComposeResult

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.actions.changespec._grouping_nav import (
    ChangeSpecGroupingNavMixin,
)
from sase.ace.tui.actions.event_handlers import EventHandlersMixin
from sase.ace.tui.actions.navigation._advanced import AdvancedNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.changespec_groups import ChangeSpecGroupingMode
from sase.ace.tui.models.group_fold import GroupFoldRegistry


def _make_changespec(
    name: str = "test_feature", *, project: str = "test"
) -> ChangeSpec:
    return ChangeSpec(
        name=name,
        description="Test description",
        parent=None,
        cl=None,
        status="Ready",
        file_path=f"/tmp/{project}/{project}.sase",
        line_number=1,
    )


def _make_agent(cl_name: str = "test_feature", *, status: str = "RUNNING") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=None,
        raw_suffix="260101_120000",
    )


class _InlineJumpApp(AdvancedNavigationMixin, ChangeSpecGroupingNavMixin):
    """Minimal changespec-tab harness for inline jump mode."""

    def __init__(self, changespecs: list[ChangeSpec]) -> None:
        self.changespecs = changespecs
        self.current_idx = 0
        self.current_tab = "changespecs"
        self._axe_items: list[Any] = []
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_target: dict[str, object] = {}
        self._entry_jump_pending_prefix = ""
        self._entry_jump_hint_to_index: dict[str, int] = {}
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._entry_jump_hint_to_banner: dict[str, Any] = {}
        self._entry_jump_banner_to_hint: dict[Any, str] = {}
        self._entry_jump_hint_to_changespec_banner: dict[str, Any] = {}
        self._entry_jump_changespec_banner_to_hint: dict[Any, str] = {}
        self._entry_jump_index_stack: dict[str, list[int]] = {}
        self._entry_jump_forward_index_stack: dict[str, list[Any]] = {}
        self._entry_jump_agents_anchor_stack: list[Any] = []
        self._entry_jump_agents_forward_anchor_stack: list[Any] = []
        self._changespec_grouping_mode = ChangeSpecGroupingMode.BY_PROJECT
        self._changespec_group_fold_registry = GroupFoldRegistry()
        self._current_changespec_group_key: tuple[str, ...] | None = None
        self.refreshes = 0
        self.jump_footer_updates = 0
        self.notify = MagicMock()

    def _refresh_current_tab(self) -> None:
        self.refreshes += 1

    def _refresh_display(self) -> None:
        self.refreshes += 1

    def _update_jump_footer(self) -> None:
        self.jump_footer_updates += 1


class _InlineJumpEventApp(EventHandlersMixin):
    """Small event-handler harness that records jump keys."""

    def __init__(self) -> None:
        self._entry_jump_mode_active = True
        self.handled_keys: list[str] = []
        self.activity_recorded = False

    def _record_input_event(self) -> None:
        self.activity_recorded = True

    def _handle_entry_jump_key(self, key: str) -> bool:
        self.handled_keys.append(key)
        return True


class _KeyEvent:
    def __init__(self, key: str, character: str | None) -> None:
        self.key = key
        self.character = character
        self.prevented = False
        self.stopped = False

    def prevent_default(self) -> None:
        self.prevented = True

    def stop(self) -> None:
        self.stopped = True


class _JumpAllTestApp(App[object | None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()
