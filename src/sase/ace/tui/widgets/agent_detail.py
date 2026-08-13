"""Agent detail widget for the ace TUI."""

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from sase.agent.status_buckets import (
    ACTIVE_PLAN_HANDOFF_STATUSES,
    PENDING_PLAN_REVIEW_STATUSES,
)

from ..tools import supports_slow_tool_sources
from ..models.agent import Agent, AgentType
from ..models.agent_tribe_summary import (
    AgentTribeSummarySnapshot,
    TribePanelIdentity,
)
from ._agent_detail_panels import (
    AgentDetailPanelMixin,
    DetailPanelMode,
)
from .file_panel import AgentFilePanel
from .file_panel._messages import LinkedDeltasRefreshed
from .prompt_panel import AgentPromptPanel
from .prompt_panel._agent_display_header_summary import (
    detail_header_summary_is_complete,
    get_cached_detail_header_summary,
)
from .prompt_panel._agent_display_state import AgentHintRender
from .tools_panel import AgentToolsPanel, ToolDetailLevel
from ..util.trace import tui_trace


_ACTIVE_STATUSES = frozenset(
    {
        "RUNNING",
        "WAITING",
        "QUEUED",
        "WAITING INPUT",
        *PENDING_PLAN_REVIEW_STATUSES,
        *ACTIVE_PLAN_HANDOFF_STATUSES,
        "QUESTION",
        "ANSWERED",
        "RETRYING",
    }
)


class AgentMetadataIdentityChanged(Message):
    """The document represented by the metadata panel changed identity."""

    def __init__(self, identity: object | None) -> None:
        super().__init__()
        self.identity = identity


class AgentDetail(AgentDetailPanelMixin, Static):
    """Combined widget with prompt and file panels."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the agent detail view."""
        super().__init__(**kwargs)
        self._layout_swapped: bool = False
        self._panel_mode: DetailPanelMode = DetailPanelMode.AUTO
        self._current_agent: Agent | None = None
        self._current_tribe_identity: TribePanelIdentity | None = None
        self._has_file_content: bool = False
        self._has_tools_content: bool = False
        self._file_count: int = 0
        self._file_index: int = 0
        self._file_visible_lines: int = 0
        self._file_total_lines: int = 0
        self._file_content_capped: bool = False
        self._attempt_view_mode: str = "merged"
        self._current_attempt_number: int | None = None
        # Two-phase update guard. ``update_display_immediate`` and
        # ``update_display`` both bump this counter; debounced workers
        # capture the value at start and discard their result if the
        # generation has advanced before they complete.
        self._agent_detail_generation: int = 0

    def compose(self) -> ComposeResult:
        """Compose the two-panel layout (prompt and file)."""
        with Vertical(id="agent-detail-layout"):
            with VerticalScroll(id="agent-prompt-scroll"):
                yield AgentPromptPanel(id="agent-prompt-panel")
            with VerticalScroll(id="agent-search-scroll", classes="hidden"):
                yield Static(id="agent-search-panel")
            yield Static(id="agent-search-command", classes="hidden")
            with VerticalScroll(id="agent-file-scroll"):
                yield AgentFilePanel(id="agent-file-panel")
            with VerticalScroll(id="agent-tools-scroll", classes="hidden"):
                yield AgentToolsPanel(id="agent-tools-panel")

    @property
    def metadata_identity(self) -> object | None:
        """Return a stable identity for the document in the metadata panel."""
        tribe_identity = getattr(self, "_current_tribe_identity", None)
        if tribe_identity is not None:
            return ("tribe", tribe_identity)
        current_agent = getattr(self, "_current_agent", None)
        if current_agent is not None:
            return (
                "agent",
                current_agent.identity,
                getattr(self, "_current_attempt_number", None),
            )
        return None

    def _active_metadata_scroll(self) -> VerticalScroll:
        """Return the search overlay or the native prompt scroll."""
        search_scroll = self.query_one("#agent-search-scroll", VerticalScroll)
        if not search_scroll.has_class("hidden"):
            return search_scroll
        return self.query_one("#agent-prompt-scroll", VerticalScroll)

    def _publish_metadata_identity_change(self, previous: object | None) -> None:
        current = self.metadata_identity
        if current != previous:
            self.post_message(AgentMetadataIdentityChanged(current))

    def update_display(
        self,
        agent: Agent,
        stale_threshold_seconds: int = 10,
        attempt_number: int | None = None,
    ) -> None:
        """Update panels with agent information.

        For NO CHANGES agents, shows only prompt panel (with reply embedded).
        For NEW PR and NEW PROPOSAL agents, shows prompt and static file panels.
        For running agents, shows prompt and auto-refreshing file panels.

        Args:
            agent: The Agent to display.
            stale_threshold_seconds: Diffs older than this are refetched.
            attempt_number: When non-None, pin the detail view to the matching
                prior-attempt record (shows full error + that attempt's reply).
        """
        previous_identity = self.metadata_identity
        self._agent_detail_generation += 1
        self._current_tribe_identity = None
        with tui_trace("widget.agent_detail.update_display", status=agent.status):
            self._update_display_impl(
                agent,
                stale_threshold_seconds=stale_threshold_seconds,
                attempt_number=attempt_number,
            )
        self._publish_metadata_identity_change(previous_identity)

    def update_display_immediate(
        self,
        agent: Agent,
        attempt_number: int | None = None,
    ) -> None:
        """Phase-5 immediate path: refresh prompt header without spawning workers.

        Called synchronously from the j/k debounced refresh so the user sees
        the new agent's title/status and any cached prompt content with no
        latency, while the file/tools/diff workers wait for the detail
        debouncer to settle on a final selection.
        """
        previous_identity = self.metadata_identity
        self._agent_detail_generation += 1
        self._current_tribe_identity = None
        with tui_trace(
            "widget.agent_detail.update_display_immediate", status=agent.status
        ):
            self._current_agent = agent
            self._current_attempt_number = attempt_number
            prompt_panel = self.query_one("#agent-prompt-panel", AgentPromptPanel)
            prompt_panel.attempt_view_mode = self._attempt_view_mode
            prompt_panel.attempt_pinned_number = attempt_number
            prompt_panel.update_header_only(agent)
        self._publish_metadata_identity_change(previous_identity)

    def _update_display_impl(
        self,
        agent: Agent,
        stale_threshold_seconds: int = 10,
        attempt_number: int | None = None,
    ) -> None:
        prompt_panel = self.query_one("#agent-prompt-panel", AgentPromptPanel)
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        tools_panel = self.query_one("#agent-tools-panel", AgentToolsPanel)

        # Detect agent change and reset per-agent state, but preserve the
        # user's explicit panel mode choice so that e.g. pressing ']' to show
        # tools persists across j/k navigation.
        prev_agent = self._current_agent
        self._current_agent = agent
        self._current_attempt_number = attempt_number
        if prev_agent is not None and prev_agent.identity != agent.identity:
            self._has_file_content = False
            self._has_tools_content = False
            # Reset from TOOLS mode when switching to non-agent entry
            if (
                not supports_slow_tool_sources(agent)
                and self._panel_mode == DetailPanelMode.TOOLS
            ):
                self._panel_mode = DetailPanelMode.AUTO
            if self._panel_mode != DetailPanelMode.TOOLS:
                tools_scroll = self.query_one("#agent-tools-scroll", VerticalScroll)
                tools_scroll.add_class("hidden")

        prompt_panel.attempt_view_mode = self._attempt_view_mode
        prompt_panel.attempt_pinned_number = attempt_number
        generation = self._agent_detail_generation

        set_render_context = getattr(
            prompt_panel, "set_agent_detail_render_context", None
        )
        if callable(set_render_context):
            set_render_context(
                generation=generation,
                attempt_view_mode=self._attempt_view_mode,
                attempt_pinned_number=attempt_number,
                is_current=self._is_agent_detail_render_current,
            )

        if self._should_render_workflow_detail_async(agent, attempt_number):
            prompt_panel.start_workflow_detail_render(
                agent,
                generation=generation,
                attempt_view_mode=self._attempt_view_mode,
                attempt_pinned_number=attempt_number,
                is_current=self._is_agent_detail_render_current,
            )
        else:
            prompt_panel.update_display(agent)

        if agent.is_clan_container:
            # Synthetic clans have no files or tools of their own. Keep their
            # aggregate detail document on the full pane and avoid launching
            # any secondary-panel work from stale prior selections.
            self._has_file_content = False
            self._has_tools_content = False
            self._file_count = 0
            self._file_index = 0
            self._file_visible_lines = 0
            self._file_total_lines = 0
            self._file_content_capped = False
            file_panel.show_empty()
            tools_panel.show_empty()
            tools_scroll = self.query_one("#agent-tools-scroll", VerticalScroll)
            tools_scroll.add_class("hidden")
            self._expand_prompt_only()
            self._update_panel_indicators()
            return
        self._update_panel_indicators()

        # Attempt-pinned view: bypass file/tools panels — we can't
        # reconstruct per-attempt file or tool history from the archived
        # snapshots. Expand the prompt panel to fill the area.
        if attempt_number is not None:
            self._expand_prompt_only()
            return

        # Probe tools availability in the background so that
        # _has_tools_content is accurate for panel mode cycling.
        # Skip the probe when the same agent is still selected and we're in
        # INFO mode — the tools panel is hidden anyway and the cache will
        # be checked when the user toggles to tools mode.
        same_agent = prev_agent is not None and prev_agent.identity == agent.identity
        if supports_slow_tool_sources(agent) and not (
            same_agent and self._panel_mode == DetailPanelMode.INFO
        ):
            tools_panel.update_display(
                agent, stale_threshold_seconds=stale_threshold_seconds
            )

        # INFO mode: only update prompt, hide both secondary panels
        if self._panel_mode == DetailPanelMode.INFO:
            file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
            prompt_scroll = self._active_metadata_scroll()
            file_scroll.add_class("hidden")
            prompt_scroll.add_class("expanded")
            return

        # When tools panel is visible, keep it showing and just refresh data
        if self._panel_mode == DetailPanelMode.TOOLS:
            # Still update file panel in background (for when tools is toggled off)
            if agent.status in _ACTIVE_STATUSES:
                file_panel.update_display(
                    agent, stale_threshold_seconds=stale_threshold_seconds
                )
            return

        # Bash/python workflow steps don't have files - expand prompt
        if agent.is_workflow_child and agent.step_type in ("bash", "python"):
            self._expand_prompt_only()
            return

        if agent.status in _ACTIVE_STATUSES:
            # Show auto-refreshing file panel for active agents
            # Don't change visibility here - let update_display() handle it
            # via FileVisibilityChanged message after fetching/validating the file
            file_panel.update_display(
                agent, stale_threshold_seconds=stale_threshold_seconds
            )
        else:
            # DONE, FAILED, etc.
            from .prompt_panel._agent_commits import agent_commit_diffs

            if agent_commit_diffs(agent):
                file_panel.update_display(
                    agent, stale_threshold_seconds=stale_threshold_seconds
                )
            elif files := agent.all_files:
                file_panel.set_file_list(files, start_index=0)
            elif agent.workspace_num is not None:
                # No saved diff file — try fetching committed diff from workspace
                file_panel.update_display(
                    agent, stale_threshold_seconds=stale_threshold_seconds
                )
            else:
                self._expand_prompt_only()

    def _should_render_workflow_detail_async(
        self, agent: Agent, attempt_number: int | None
    ) -> bool:
        return (
            attempt_number is None
            and agent.agent_type == AgentType.WORKFLOW
            and not agent.is_workflow_child
            and not agent.appears_as_agent
        )

    def _is_agent_detail_render_current(
        self,
        agent_identity: tuple[Any, ...],
        worker_generation: int,
        attempt_view_mode: str,
        attempt_pinned_number: int | None,
    ) -> bool:
        """Return whether an async prompt result still matches the detail view."""
        return (
            self._agent_detail_generation == worker_generation
            and self._current_agent is not None
            and self._current_agent.identity == agent_identity
            and self._attempt_view_mode == attempt_view_mode
            and self._current_attempt_number == attempt_pinned_number
        )

    def update_display_with_hints(self, agent: Agent) -> AgentHintRender:
        """Re-render the prompt panel with file path hints.

        Scans xprompt, prompt, and chat sections for file paths and
        inserts numbered ``[N]`` markers.  Returns the hint mappings so
        the caller can process user selections.  Advancing the detail
        generation first prevents deferred work from the preceding plain
        render from replacing the annotated prompt.

        Args:
            agent: The Agent to display with hints.

        Returns:
            File hint mappings and deferred tool-call report specs.
        """
        previous_identity = self.metadata_identity
        self._agent_detail_generation += 1
        self._current_tribe_identity = None
        prompt_panel = self.query_one("#agent-prompt-panel", AgentPromptPanel)
        cancel_slow_tick = getattr(prompt_panel, "_cancel_slow_tool_render_tick", None)
        if callable(cancel_slow_tick):
            cancel_slow_tick()
        prompt_panel.attempt_view_mode = self._attempt_view_mode
        prompt_panel.attempt_pinned_number = self._current_attempt_number
        generation = self._agent_detail_generation

        set_render_context = getattr(
            prompt_panel, "set_agent_detail_render_context", None
        )
        if callable(set_render_context):
            set_render_context(
                generation=generation,
                attempt_view_mode=self._attempt_view_mode,
                attempt_pinned_number=self._current_attempt_number,
                is_current=self._is_agent_detail_render_current,
            )
        result = prompt_panel.update_display_with_hints(agent)
        self._publish_metadata_identity_change(previous_identity)
        return result

    def hint_document_is_current(self, agent: Agent) -> bool:
        """Return whether the visible hint document already matches ``agent``."""
        prompt_panel = self.query_one("#agent-prompt-panel", AgentPromptPanel)
        prompt_panel.attempt_view_mode = self._attempt_view_mode
        prompt_panel.attempt_pinned_number = self._current_attempt_number
        return prompt_panel.hint_document_is_current(agent)

    def detail_header_summary_complete(self, agent: Agent) -> bool:
        """Return whether every SASE CONTEXT lane has resolved for ``agent``.

        Lets a hint-mode repaint override the "hint input has a value"
        suppression once streaming (bead sase-l6.4) finishes the last lane,
        instead of leaving the document stuck on a partial render for the
        rest of the hint session.
        """
        prompt_panel = self.query_one("#agent-prompt-panel", AgentPromptPanel)
        summary = get_cached_detail_header_summary(prompt_panel, agent)
        return detail_header_summary_is_complete(summary)

    def show_empty(self) -> None:
        """Show empty state for all panels."""
        previous_identity = self.metadata_identity
        self._agent_detail_generation += 1
        self._current_agent = None
        self._current_tribe_identity = None
        self._current_attempt_number = None
        prompt_panel = self.query_one("#agent-prompt-panel", AgentPromptPanel)
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        tools_panel = self.query_one("#agent-tools-panel", AgentToolsPanel)

        prompt_panel.show_empty()
        file_panel.show_empty()
        tools_panel.show_empty()

        # Hide file and tools panels when no agent is selected
        prompt_scroll = self._active_metadata_scroll()
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        tools_scroll = self.query_one("#agent-tools-scroll", VerticalScroll)
        file_scroll.add_class("hidden")
        tools_scroll.add_class("hidden")
        prompt_scroll.add_class("expanded")
        self._panel_mode = DetailPanelMode.AUTO
        self._has_file_content = False
        self._has_tools_content = False
        self._file_count = 0
        self._file_index = 0
        self._file_visible_lines = 0
        self._file_total_lines = 0
        self._file_content_capped = False
        prompt_scroll.border_subtitle = ""
        file_scroll.border_title = ""
        file_scroll.border_subtitle = ""
        self._publish_metadata_identity_change(previous_identity)

    def show_tribe_summary(
        self,
        snapshot: AgentTribeSummarySnapshot,
        *,
        cheap: bool = False,
    ) -> None:
        """Show a tribe document on the regular fold-aware prompt surface."""
        previous_identity = self.metadata_identity
        self._agent_detail_generation += 1
        self._current_agent = None
        self._current_tribe_identity = snapshot.container_identity
        self._current_attempt_number = None
        prompt_panel = self.query_one("#agent-prompt-panel", AgentPromptPanel)
        prompt_panel.update_tribe_display(snapshot, cheap=cheap)
        prompt_scroll = self._active_metadata_scroll()
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        tools_scroll = self.query_one("#agent-tools-scroll", VerticalScroll)
        file_scroll.add_class("hidden")
        tools_scroll.add_class("hidden")
        prompt_scroll.add_class("expanded")
        prompt_scroll.remove_class("layout-priority")
        self._has_file_content = False
        self._has_tools_content = False
        prompt_scroll.border_subtitle = ""
        self._publish_metadata_identity_change(previous_identity)

    def refresh_current_file(self, agent: Agent) -> None:
        """Force refresh the file for the given agent.

        Args:
            agent: The Agent to refresh file for.
        """
        from ..util.trace import tui_trace

        with tui_trace("agent_detail.refresh_current_file"):
            file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
            file_panel.refresh_file(agent)

    def cycle_next_file(self) -> None:
        """Cycle to the next file in the file panel."""
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        file_panel.next_file()

    def cycle_prev_file(self) -> None:
        """Cycle to the previous file in the file panel."""
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        file_panel.prev_file()

    def on_linked_deltas_refreshed(self, message: LinkedDeltasRefreshed) -> None:
        """Refresh file-panel linked pages after the prompt worker updates cache."""
        if (
            self._current_agent is None
            or self._current_agent.identity != message.agent_identity
        ):
            return
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        file_panel._reconcile_file_list(
            self._current_agent,
            allow_initial_display=True,
        )
        message.stop()

    def toggle_layout(self) -> None:
        """Toggle between default (30/70) and swapped (70/30) layout."""
        prompt_scroll = self._active_metadata_scroll()

        self._layout_swapped = not self._layout_swapped

        # Apply layout classes to whichever panel (file or tools) is visible
        if self.is_tools_visible():
            secondary_scroll = self.query_one("#agent-tools-scroll", VerticalScroll)
        else:
            secondary_scroll = self.query_one("#agent-file-scroll", VerticalScroll)

        if self._layout_swapped:
            prompt_scroll.add_class("layout-priority")
            secondary_scroll.add_class("layout-secondary")
        else:
            prompt_scroll.remove_class("layout-priority")
            secondary_scroll.remove_class("layout-secondary")

    def is_tools_visible(self) -> bool:
        """Check if the tools panel is currently visible.

        Returns:
            True if the tools panel is visible, False otherwise.
        """
        return self._current_agent is not None and (
            self._panel_mode == DetailPanelMode.TOOLS
        )

    @property
    def tools_detail_level(self) -> ToolDetailLevel:
        """Current detail level for the tools panel."""
        tools_panel = self.query_one("#agent-tools-panel", AgentToolsPanel)
        return tools_panel.detail_level

    def expand_tools_detail(self) -> bool:
        """Expand the visible tools panel by one detail level."""
        tools_panel = self.query_one("#agent-tools-panel", AgentToolsPanel)
        return tools_panel.expand_detail()

    def collapse_tools_detail(self) -> bool:
        """Collapse the visible tools panel by one detail level."""
        tools_panel = self.query_one("#agent-tools-panel", AgentToolsPanel)
        return tools_panel.collapse_detail()

    def set_tools_detail_level(self, level: ToolDetailLevel | int) -> bool:
        """Set the visible tools panel detail level."""
        tools_panel = self.query_one("#agent-tools-panel", AgentToolsPanel)
        return tools_panel.set_detail_level(level)

    def is_info_mode(self) -> bool:
        """Check if the panel is in info-only mode.

        Returns:
            True if in INFO mode (prompt at 100%), False otherwise.
        """
        return self._panel_mode == DetailPanelMode.INFO

    def is_file_visible(self) -> bool:
        """Check if the file panel is currently visible.

        Returns:
            True if the file panel is visible, False otherwise.
        """
        if self._current_agent is None:
            return False
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        return not file_scroll.has_class("hidden")

    def get_editor_file_info(self) -> tuple[str | None, str | None, str]:
        """Get file path, content, and suffix for opening in an editor.

        Returns:
            (file_path, content, suffix) where:
            - file_path is set if a real file can be opened directly
            - content is set if a temp file should be created
            - suffix is the file extension for the temp file
        """
        if self.is_file_visible():
            file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
            return (
                file_panel.get_current_file_path(),
                file_panel.get_current_content(),
                ".diff",
            )
        if self.is_tools_visible():
            tools_panel = self.query_one("#agent-tools-panel", AgentToolsPanel)
            return (None, tools_panel.get_tools_text(), ".md")
        return (None, None, "")

    def get_current_image_path(self) -> str | None:
        """Return the currently visible image path, or None."""
        if not self.is_file_visible():
            return None
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        return file_panel.get_current_image_path()

    def is_layout_swapped(self) -> bool:
        """Check if the layout is currently swapped.

        Returns:
            True if prompt has priority (70/30), False if default (30/70).
        """
        return self._layout_swapped

    @property
    def attempt_view_mode(self) -> str:
        """Current mode for rendering the attempt history ("merged" or "current-only")."""
        return self._attempt_view_mode

    def toggle_attempt_view(self) -> bool:
        """Cycle between merged / current-only attempt view modes.

        Returns True if the view was re-rendered (an agent is selected).
        """
        self._attempt_view_mode = (
            "current-only" if self._attempt_view_mode == "merged" else "merged"
        )
        if self._current_agent is not None:
            self.update_display(
                self._current_agent, attempt_number=self._current_attempt_number
            )
            return True
        return False
