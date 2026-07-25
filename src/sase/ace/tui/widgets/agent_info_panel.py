"""Agent info panel widget for the ace TUI."""

from typing import Any

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from ..agent_count_chip import AGENT_COUNT_CHIP_QUEUED_STYLE
from ..keymaps import KeymapRegistry, key_display_name, load_keymap_registry


class AgentInfoPanel(Static):
    """Top bar showing agent metrics and auto-refresh countdown."""

    _TOTAL_COUNT_STYLE = "bold #FFFFFF"
    # Keep the neutral denominator in its own Rich span while matching adjacent
    # dim labels.  The explicit non-bold flag prevents modal overlays from
    # coalescing those spans and perturbing neighboring glyph antialiasing.
    _NEUTRAL_RUNNER_LIMIT_STYLE = Style(
        bold=False,
        dim=True,
    )

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the info panel."""
        super().__init__(**kwargs)
        self._position = 0
        self._total = 0
        self._unread_count = 0
        self._asking_count = 0
        self._starting_count = 0
        self._running_count = 0
        self._waiting_count = 0
        self._failed_count = 0
        self._read_count = 0
        self._agent_lane_count = 0
        self._runner_limit = 0
        self._runner_queue_count = 0
        self._neighbor_count = 0
        self._countdown = 0
        self._interval = 0
        self._view_mode: str = ""
        self._grouping_mode: str = ""
        self._search_query: str = ""
        self._loading: bool = False
        self._registry = load_keymap_registry({})

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Override the keymap registry and refresh display."""
        self._registry = registry
        self._update_display()

    def set_loading(self, loading: bool) -> None:
        """Show or hide the startup-loading ellipsis.

        While True, the count line renders ``Agents: …`` (dim italic) to
        signal that agent data has not yet loaded, rather than falsely
        claiming the list is empty.
        """
        if self._loading != loading:
            self._loading = loading
            self._update_display()

    def update_position(self, position: int, total: int) -> None:
        """Store the current position for compatibility with existing callers.

        Args:
            position: Current position (1-based for display).
            total: Total number of agents.
        """
        self._position = position
        self._total = total
        self._update_display()

    def update_agent_counts(
        self,
        unread: int,
        asking: int,
        running: int,
        waiting: int,
        failed: int,
        read: int,
        total: int,
        *,
        starting: int = 0,
    ) -> None:
        """Compatibility adapter for the headline and concrete metric strip.

        Args:
            unread: Visible unread completed agent count.
            asking: Visible agent count paused for human input.
            starting: Visible pre-run agent count.
            running: Visible active agent count, excluding waiting agents.
            waiting: Visible waiting agent count.
            failed: Visible failed agent count.
            read: Visible completed agent count that has already been read.
            total: Agent-lane count rendered as the leading headline value.
        """
        self._unread_count = unread
        self._asking_count = asking
        self._starting_count = starting
        self._running_count = running
        self._waiting_count = waiting
        self._failed_count = failed
        self._read_count = read
        self._agent_lane_count = total
        self._update_display()

    def update_countdown(self, countdown: int, interval: int) -> None:
        """Update the countdown display.

        Args:
            countdown: Seconds remaining until auto-refresh.
            interval: Total refresh interval in seconds.
        """
        self._countdown = countdown
        self._interval = interval
        self._update_display()

    def update_runner_capacity(
        self,
        effective_limit: int,
        queue_count: int,
    ) -> None:
        """Update the cached global user-agent runner capacity snapshot."""
        self._runner_limit = effective_limit
        self._runner_queue_count = queue_count
        self._update_display()

    def update_view_mode(self, mode: str) -> None:
        """Update the panel view mode indicator.

        Args:
            mode: The current view mode label (``"file"``, ``"tools"``,
                ``"collapsed"``, or ``"summary"``). Empty string hides the
                indicator.
        """
        self._view_mode = mode
        self._update_display()

    def update_grouping_mode(self, label: str) -> None:
        """Update the active grouping-strategy label.

        Args:
            label: Human-readable label for the active grouping strategy
                (``"by project"``, ``"by date"``, ``"by status"``).  The
                badge is always rendered, so an empty string is treated
                as ``"by project"``.
        """
        self._grouping_mode = label
        self._update_display()

    def update_search_query(self, query: str) -> None:
        """Update the search query filter display.

        Args:
            query: The current search query string. Empty string hides the filter.
        """
        self._search_query = query
        self._update_display()

    def update_state(
        self,
        *,
        position: int,
        total: int,
        unread: int,
        asking: int,
        running: int,
        waiting: int,
        failed: int,
        read: int,
        agent_lane_count: int,
        starting: int,
        neighbor_count: int = 0,
        countdown: int,
        interval: int,
        view_mode: str,
        grouping_mode: str,
        search_query: str,
        runner_limit: int = 0,
        runner_queue_count: int = 0,
    ) -> None:
        """Batch all logical info-panel state into one render.

        Stable state (counts, position, modes, query) controls whether the
        whole Rich ``Text`` is rebuilt. Countdown ticks alone are routed
        through :meth:`update_countdown_only`, which avoids reinvalidating
        the stable cache and requests a no-layout repaint.
        """
        new_stable = (
            position,
            total,
            unread,
            asking,
            starting,
            running,
            waiting,
            failed,
            read,
            agent_lane_count,
            runner_limit,
            runner_queue_count,
            max(0, neighbor_count),
            view_mode,
            grouping_mode,
            search_query,
        )
        old_stable = (
            self._position,
            self._total,
            self._unread_count,
            self._asking_count,
            self._starting_count,
            self._running_count,
            self._waiting_count,
            self._failed_count,
            self._read_count,
            self._agent_lane_count,
            self._runner_limit,
            self._runner_queue_count,
            self._neighbor_count,
            self._view_mode,
            self._grouping_mode,
            self._search_query,
        )
        if new_stable == old_stable:
            self.update_countdown_only(countdown, interval)
            return
        (
            self._position,
            self._total,
            self._unread_count,
            self._asking_count,
            self._starting_count,
            self._running_count,
            self._waiting_count,
            self._failed_count,
            self._read_count,
            self._agent_lane_count,
            self._runner_limit,
            self._runner_queue_count,
            self._neighbor_count,
            self._view_mode,
            self._grouping_mode,
            self._search_query,
        ) = new_stable
        self._countdown = countdown
        self._interval = interval
        self._update_display()

    def update_countdown_only(self, countdown: int, interval: int) -> None:
        """Refresh countdown without rebuilding stable panel content.

        Returns early when the rendered countdown text is unchanged.
        Otherwise emits a ``layout=False`` repaint, since the info panel
        is always one line and its size cannot change.
        """
        if self._countdown == countdown and self._interval == interval:
            return
        self._countdown = countdown
        self._interval = interval
        self._render_panel_text(layout=False)

    _VIEW_MODE_STYLES: dict[str, str] = {
        "file": "bold green",
        "tools": "bold #87D7FF",
        "collapsed": "dim italic",
        "summary": "bold #FFD75F",
    }

    _GROUPING_MODE_STYLES: dict[str, str] = {
        "by project": "bold #5FAFFF",
        "by date": "bold #87D7FF",
        "by status": "bold #FFAF87",
    }

    _COUNT_STYLES: dict[str, str] = {
        "asking": "bold #FFAF00",
        "starting": "bold #1a1a1a on #87D7FF",
        "running": "bold #00D7AF",
        "waiting": "bold #AF87FF",
        "failed": "bold #FF5F5F",
        "unread": "bold #1a1a1a on #FFD700",
        "read": "bold #5FD7FF",
    }

    _COUNT_LABELS: dict[str, str] = {
        "asking": "stopped",
        "read": "done",
    }

    def _metric_counts(self) -> list[tuple[str, int]]:
        return [
            ("asking", self._asking_count),
            ("starting", self._starting_count),
            ("waiting", self._waiting_count),
            ("failed", self._failed_count),
            ("unread", self._unread_count),
            ("read", self._read_count),
        ]

    def _runner_limit_style(self) -> str | Style:
        """Return the runner-limit style for the current capacity pressure."""
        limit = self._runner_limit
        running = self._running_count
        if limit <= 0:
            return self._NEUTRAL_RUNNER_LIMIT_STYLE
        if running >= limit:
            return "bold #FF5F5F"
        if running >= (3 * limit + 3) // 4:
            return "bold #FF8700"
        if running >= (limit + 1) // 2:
            return "bold #FFD700"
        return self._NEUTRAL_RUNNER_LIMIT_STYLE

    def _append_status_strip(self, text: Text) -> None:
        """Append the consolidated visible status and runner-capacity strip."""
        text.append("  [", style="dim")
        # The runner-limit style already escalates with capacity pressure, so the
        # running count itself stays a single stable color at every occupancy.
        text.append(str(self._running_count), style=self._COUNT_STYLES["running"])
        text.append("/", style="dim")
        text.append(str(self._runner_limit), style=self._runner_limit_style())
        text.append(" running", style="dim")

        if self._runner_queue_count > 0:
            text.append(" · ", style="dim")
            text.append(
                str(self._runner_queue_count),
                style=AGENT_COUNT_CHIP_QUEUED_STYLE,
            )
            text.append(" queued", style="dim")

        metrics = [(label, count) for label, count in self._metric_counts() if count]
        for label, count in metrics:
            text.append(" · ", style="dim")
            count_style = self._COUNT_STYLES[label]
            text.append(f"{count}", style=count_style)
            suffix = f" {self._COUNT_LABELS.get(label, label)}"
            label_style = count_style if label in {"starting", "unread"} else "dim"
            text.append(suffix, style=label_style)
        text.append("]", style="dim")

    def _append_neighbor_badge(self, text: Text) -> None:
        if self._neighbor_count <= 0:
            return
        key = key_display_name(self._registry.app.start_sibling_mode)
        text.append("   ")
        text.append("[", style="dim")
        text.append("neighbors: ", style="dim")
        text.append(str(self._neighbor_count), style="bold #00D7AF")
        text.append(f" ({key})", style="dim")
        text.append("]", style="dim")

    def _build_display_text(self) -> Text:
        """Build the full Rich ``Text`` for the current panel state."""
        text = Text()
        if self._loading:
            text.append("Agents", style="bold #87D7FF")
            text.append(": ", style="bold #87D7FF")
            text.append("…", style="dim italic")
            return text
        text.append(f"{self._agent_lane_count}", style=self._TOTAL_COUNT_STYLE)
        self._append_status_strip(text)
        self._append_neighbor_badge(text)
        if self._search_query:
            text.append("   ")
            text.append("filter: ", style="dim italic")
            text.append(self._search_query, style="bold #FFD700")
        if self._view_mode:
            text.append("   ")
            text.append("[", style="dim")
            text.append("view: ", style="dim")
            style = self._VIEW_MODE_STYLES.get(self._view_mode, "dim")
            text.append(self._view_mode, style=style)
            text.append("]", style="dim")
        grouping_label = self._grouping_mode or "by project"
        text.append("   ")
        text.append("[", style="dim")
        text.append("group: ", style="dim")
        text.append(
            grouping_label,
            style=self._GROUPING_MODE_STYLES.get(grouping_label, "dim"),
        )
        key = key_display_name(self._registry.app.cycle_grouping_mode)
        text.append(f" ({key})", style="dim")
        text.append("]", style="dim")
        if self._interval > 0:
            text.append("   ")
            text.append("(auto-refresh in ", style="dim")
            text.append(f"{self._countdown}s", style="bold #FFD700")
            text.append(")", style="dim")
        return text

    def _render_panel_text(self, *, layout: bool) -> None:
        """Push the current display text to the Static base.

        The info panel is always one line tall, so callers should pass
        ``layout=False`` whenever they know the rebuild cannot change the
        widget's height (e.g. countdown ticks). A ``TypeError`` from older
        Textual versions that lack the ``layout`` kwarg falls back to the
        default behavior.
        """
        text = self._build_display_text()
        try:
            self.update(text, layout=layout)
        except TypeError:
            self.update(text)

    def _update_display(self) -> None:
        """Refresh the displayed text after a stable-state change."""
        self._render_panel_text(layout=False)
