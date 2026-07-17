"""Local telemetry dashboard pane for the SASE Admin Center."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.align import Align
from rich.panel import Panel
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Horizontal, Vertical
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.keymaps import (
    TelemetryPaneKeymaps,
    build_telemetry_bindings,
    load_keymap_registry,
    telemetry_help_bindings,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.telemetry.render import render_line_chart, render_stat_tile, status_color

from .telemetry_pane_data import (
    RANGE_ORDER,
    SUBSYSTEM_LABELS,
    SUBSYSTEM_ORDER,
    TelemetryRange,
    TelemetrySubsystem,
    TelemetryViewData,
    load_telemetry_view,
)

_ACCENT = "#FF87D7"
_REFRESH_INTERVAL_SECONDS = 10.0


class TelemetryPane(Vertical):
    """Stat tiles and chart grid backed by the local Rust telemetry store."""

    can_focus = True
    BINDINGS = []

    def __init__(
        self,
        *,
        auto_load: bool = True,
        keymaps: TelemetryPaneKeymaps | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._keymaps = keymaps or load_keymap_registry({}).telemetry
        self._bindings = BindingsMap(build_telemetry_bindings(self._keymaps))
        self._subsystem: TelemetrySubsystem = "agents"
        self._range_key: TelemetryRange = "1h"
        self._auto_load = auto_load
        self._loading = False
        self._loaded_once = False
        self._worker: Worker[Any] | None = None
        self._refresh_timer: Any | None = None
        self._load_debouncer: DetailPanelDebouncer | None = None
        self._last_result: TelemetryViewData | None = None
        self._last_error = ""

    def compose(self) -> ComposeResult:
        yield Static(self._heading_text(), id="telemetry-title", markup=False)
        with Horizontal(id="telemetry-tiles"):
            for index in range(5):
                yield Static(
                    self._loading_panel("Loading", height=6),
                    id=f"telemetry-tile-{index}",
                    classes="telemetry-tile",
                )
        with Vertical(id="telemetry-charts"):
            with Horizontal(classes="telemetry-chart-row"):
                yield Static(
                    self._loading_panel("Loading telemetry", height=8),
                    id="telemetry-chart-0",
                    classes="telemetry-chart",
                )
                yield Static(
                    self._loading_panel("Loading telemetry", height=8),
                    id="telemetry-chart-1",
                    classes="telemetry-chart telemetry-chart-right",
                )
            with Horizontal(classes="telemetry-chart-row"):
                yield Static(
                    self._loading_panel("Loading telemetry", height=8),
                    id="telemetry-chart-2",
                    classes="telemetry-chart",
                )
                yield Static(
                    self._loading_panel("Loading telemetry", height=8),
                    id="telemetry-chart-3",
                    classes="telemetry-chart telemetry-chart-right",
                )
        yield Static(
            Text("Health · waiting for telemetry", style="dim"),
            id="telemetry-health",
            markup=False,
        )
        yield Static(self._hints_text(), id="telemetry-hints", markup=False)

    def on_mount(self) -> None:
        self._load_debouncer = DetailPanelDebouncer(self.app)
        self._refresh_timer = self.set_interval(
            _REFRESH_INTERVAL_SECONDS,
            self._on_refresh_tick,
        )
        if self._is_active_tab():
            self._ensure_loaded()

    def on_unmount(self) -> None:
        if self._load_debouncer is not None:
            self._load_debouncer.cancel()
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None
        if self._worker is not None:
            self._worker.cancel()

    def focus_default(self) -> None:
        """Focus this key-driven pane and lazily perform its first load."""

        self.focus()
        self._ensure_loaded()

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        """Pause pending refresh work while another Admin Center tab is active."""

        if active:
            self._ensure_loaded()
        elif self._load_debouncer is not None:
            self._load_debouncer.cancel()

    def action_cycle_subsystem(self) -> None:
        """Cycle to the next subsystem chart set."""

        index = SUBSYSTEM_ORDER.index(self._subsystem)
        self._subsystem = SUBSYSTEM_ORDER[(index + 1) % len(SUBSYSTEM_ORDER)]
        self._selection_changed()

    def action_cycle_range(self) -> None:
        """Cycle to the next telemetry time range."""

        index = RANGE_ORDER.index(self._range_key)
        self._range_key = RANGE_ORDER[(index + 1) % len(RANGE_ORDER)]
        self._selection_changed()

    def action_refresh(self) -> None:
        """Coalesce a manual refresh through the worker-backed load path."""

        self._schedule_load()

    def _selection_changed(self) -> None:
        self._last_error = ""
        self._update_heading()
        self._schedule_load()

    def _ensure_loaded(self) -> None:
        if self._auto_load and not self._loaded_once and not self._loading:
            self._start_load()

    def _schedule_load(self) -> None:
        if not self._is_active_tab():
            return
        if self._load_debouncer is None:
            self._start_load()
            return
        self._load_debouncer.schedule(self._start_load)

    def _on_refresh_tick(self) -> None:
        """Thin synchronous timer callback; all real work stays in a worker."""

        if self._is_active_tab():
            self._schedule_load()

    def _start_load(self) -> None:
        if not self._is_active_tab():
            return
        subsystem = self._subsystem
        range_key = self._range_key
        self._loading = True
        self._last_error = ""
        self._update_heading()
        if self._last_result is None:
            self._paint_loading()

        def task() -> TelemetryViewData:
            return load_telemetry_view(subsystem, range_key)

        self._worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            exit_on_error=False,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._worker:
            return
        if event.state == WorkerState.SUCCESS:
            self._loading = False
            self._loaded_once = True
            result = event.worker.result
            if not isinstance(result, TelemetryViewData):
                self._paint_error("telemetry worker returned no result")
                return
            if (
                result.subsystem != self._subsystem
                or result.range_key != self._range_key
            ):
                self._schedule_load()
                return
            self._paint_result(result)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._loaded_once = True
            message = str(event.worker.error) if event.worker.error else "load failed"
            self._paint_error(message)

    def _paint_loading(self) -> None:
        tile_width, chart_width, chart_height = self._render_sizes()
        for index in range(5):
            self._update_static(
                f"#telemetry-tile-{index}",
                self._loading_panel("Loading", width=tile_width, height=6),
            )
        for index in range(4):
            self._update_static(
                f"#telemetry-chart-{index}",
                self._loading_panel(
                    "Loading telemetry",
                    width=chart_width,
                    height=chart_height,
                ),
            )
        self._update_static(
            "#telemetry-health",
            Text("Health · loading local samples…", style="dim"),
        )

    def _paint_result(self, result: TelemetryViewData) -> None:
        self._last_result = result
        tile_width, chart_width, chart_height = self._render_sizes()
        for index, tile in enumerate(result.tiles):
            renderable = render_stat_tile(
                tile.value,
                caption=tile.caption,
                width=tile_width,
                height=6,
                key=tile.key,
                value_format=tile.value_format,
                delta=tile.delta,
                lower_is_better=tile.lower_is_better,
                sparkline=tile.sparkline,
                status=tile.status,
                recording_started_at=result.recording_started_at,
            )
            self._update_static(f"#telemetry-tile-{index}", renderable)

        for index, chart in enumerate(result.charts):
            renderable = render_line_chart(
                chart.series,
                title=chart.title,
                width=chart_width,
                height=chart_height,
                y_label=chart.y_label,
                value_format=chart.value_format,
                y_min=chart.y_min,
                y_max=chart.y_max,
                recording_started_at=result.recording_started_at,
            )
            self._update_static(f"#telemetry-chart-{index}", renderable)

        health = Text()
        if result.health_status is None:
            health.append("○ ", style="dim")
            health.append(result.health_text, style="dim")
        else:
            color = status_color(result.health_status)
            health.append("● ", style=f"bold {color}")
            health.append(result.health_text, style=color)
        self._update_static("#telemetry-health", health)
        self._update_heading()

    def _paint_error(self, message: str) -> None:
        self._last_error = message
        self._update_heading()
        self._update_static(
            "#telemetry-health",
            Text(f"● Telemetry load failed · {message}", style="bold red"),
        )
        if self._last_result is not None:
            return
        _, chart_width, chart_height = self._render_sizes()
        for index in range(4):
            self._update_static(
                f"#telemetry-chart-{index}",
                Panel(
                    Align.center(Text(message, style="red"), vertical="middle"),
                    title="Telemetry unavailable",
                    border_style="red",
                    width=chart_width,
                    height=chart_height,
                    padding=0,
                ),
            )

    def _render_sizes(self) -> tuple[int, int, int]:
        width = max(60, int(self.size.width or 100))
        height = max(20, int(self.size.height or 26))
        tile_width = max(12, (width - 4) // 5)
        chart_width = max(24, (width - 1) // 2)
        # The compact renderer uses block sparklines, which remain legible in
        # Textual's pinned Fira Code PNG renderer (braille dots do not have a
        # glyph there) and fit the Admin Center's two-row chart grid cleanly.
        chart_height = max(6, min(7, (height - 9) // 2))
        return tile_width, chart_width, chart_height

    def _heading_text(self) -> Text:
        heading = Text()
        heading.append("Telemetry", style=f"bold {_ACCENT}")
        heading.append("  ·  ")
        heading.append(SUBSYSTEM_LABELS[self._subsystem], style="bold")
        heading.append(f"  ·  {self._range_key}", style="bold #87D7FF")
        if self._loading:
            heading.append("  ·  refreshing…", style="dim italic")
        elif self._last_error:
            heading.append("  ·  load failed", style="red")
        elif self._last_result is not None:
            updated = (
                datetime.fromtimestamp(self._last_result.generated_at)
                .astimezone()
                .strftime("%H:%M:%S")
            )
            heading.append(f"  ·  updated {updated}", style="dim")
        return heading

    def _hints_text(self) -> Text:
        hints = Text(justify="center")
        styles = (f"bold {_ACCENT}", "bold #87D7FF", "bold #FFD700")
        for index, ((key, description), style) in enumerate(
            zip(telemetry_help_bindings(self._keymaps), styles, strict=True)
        ):
            if index:
                hints.append("   ")
            hints.append(key, style=style)
            hints.append(f" {description.lower()}")
        return hints

    def _update_heading(self) -> None:
        self._update_static("#telemetry-title", self._heading_text())

    def _update_static(self, selector: str, content: Any) -> None:
        try:
            self.query_one(selector, Static).update(content)
        except Exception:
            pass

    def _is_active_tab(self) -> bool:
        try:
            return getattr(self.screen, "_active_tab", None) == self.id
        except Exception:
            return False

    @staticmethod
    def _loading_panel(
        label: str,
        *,
        width: int = 18,
        height: int = 6,
    ) -> Panel:
        return Panel(
            Align.center(Text(label, style="dim italic"), vertical="middle"),
            border_style="#444444",
            width=width,
            height=height,
            padding=0,
        )


__all__ = ["TelemetryPane"]
