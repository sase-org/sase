"""Shared type hints and helpers for hint action mixins."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Import Patch and Agent unconditionally since they are used as type
# annotations in attribute declarations (not just in function signatures)
from sase.memory.legacy_glossary_read_report import GlossaryReadReportSpec
from sase.memory.memory_read_report import MemoryReadReportSpec

from ....patch import Patch
from ...artifact_reads import ArtifactReadRefSpec
from ...models.agent import Agent
from ...tools.report import SlowToolCallReportSpec
from ...widgets import HintInputBar
from ...widgets.prompt_panel._agent_display_state import AgentHintRender, CommitViewSpec


class HintMixinBase:
    """Base class providing shared type hints for all hint action mixins.

    These type hints declare attributes that are defined at runtime by AceApp.
    All hint action sub-mixins should inherit from this class.
    """

    # Patch state
    patches: list[Patch]
    current_idx: int

    # Tab and agents state
    current_tab: str
    _agents: list[Agent]

    # Hint mode state
    _hint_mode_active: bool
    _hint_mode_hints_for: str | None
    _hint_mappings: dict[int, str]
    _hint_tool_call_reports: dict[str, SlowToolCallReportSpec]
    _hint_glossary_reports: dict[str, GlossaryReadReportSpec]
    _hint_memory_reports: dict[str, MemoryReadReportSpec]
    _hint_artifact_read_refs: dict[str, ArtifactReadRefSpec]
    _hint_commit_views: dict[int, CommitViewSpec]
    _hook_hint_to_idx: dict[int, int]
    _hint_to_entry_id: dict[int, str]
    _mentor_hint_to_info: dict[int, tuple[str, str]]
    _hint_patch_name: str
    _agent_hint_render_session: int
    _agent_hint_render_identity: tuple[object, ...] | None
    _agent_hint_render_ready: asyncio.Event | None
    _agent_hint_render_task: asyncio.Task[AgentHintRender | None] | None

    # Accept mode state
    _accept_mode_active: bool
    _accept_last_base: str | None

    # Rewind mode state
    _rewind_mode_active: bool

    # Failed hooks state
    _failed_hooks_targets: list[str]
    _failed_hooks_file_path: str | None

    def _hint_input_bar_active(self) -> bool:
        """Return whether any transient hint input mode is active."""
        return (
            self._hint_mode_active
            or self._accept_mode_active
            or self._rewind_mode_active
        )

    def _refocus_existing_hint_bar(self) -> bool:
        """Focus an already-mounted hint bar, if present.

        Returns ``True`` when a bar exists so callers can avoid mounting a
        duplicate ``#hint-input-bar`` while Textual still has the id registered.
        """
        from textual.css.query import NoMatches

        query_one = getattr(self, "query_one", None)
        if not callable(query_one):
            return False

        try:
            hint_bar = query_one("#hint-input-bar", HintInputBar)
        except NoMatches:
            return False

        try:
            hint_input = hint_bar.query_one("#hint-input")
            hint_input.focus()
        except Exception:
            pass
        return True

    def _cancel_agent_hint_render_tasks(self) -> None:
        """Cancel the current Agents-tab hint render and release its waiters."""
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None
        for task in tuple(getattr(self, "_agent_hint_render_tasks", ())):
            if task is not current_task:
                task.cancel()

        ready = getattr(self, "_agent_hint_render_ready", None)
        if ready is not None:
            ready.set()
        self._agent_hint_render_session = (
            getattr(self, "_agent_hint_render_session", 0) + 1
        )
        self._agent_hint_render_identity = None
        self._agent_hint_render_ready = None
        self._agent_hint_render_task = None
