"""Display, selection, and bucket navigation for the Models panel."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.geometry import Size
from textual.widgets import OptionList, Static

from sase.llm_provider import (
    AliasView,
    BucketView,
)

from .models_panel_display_options import ModelsPanelDisplayOptionsMixin
from .models_panel_rendering import (
    OWNERSHIP_ACCENT,
    custom_builtin_shadow_warning_message,
    description_text_for_row,
)
from .models_panel_rows import (
    BigEpicPhaseThresholdSettingRow,
    DefaultEffortSettingRow,
    LaunchModelSettingRow,
    ModelsPanelDisplayRow,
    RunnerLimitSettingRow,
)

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object

# Mirrors the #models-panel-container / #models-panel-description /
# #models-panel-footer budget documented in styles.tcss. Kept in Python
# (rather than expressed purely in CSS) because Textual's "auto" and "fr"
# layout units cannot express "shrink the list only when the other rows
# actually need the room" without also forcing the list to balloon to its
# 22-row cap for short lists that never needed the extra space.
_MODAL_MAX_HEIGHT_ROWS = 39
_MODAL_CHROME_ROWS = 4  # container border (2) + padding-vertical (2)
_MODAL_CHROME_COLS = 6  # container border (2) + padding-horizontal (4)
_MODAL_WIDTH = 110
_TITLE_MARGIN_ROWS = 1
_DESCRIPTION_MARGIN_ROWS = 1
_DESCRIPTION_MIN_BOX_ROWS = 4  # border-top (1) + padding-top (1) + 2 content rows
_FOOTER_CHROME_ROWS = 3  # border-top (1) + padding-top (1) + margin-top (1)
_LIST_MIN_VIEWPORT_ROWS = 6  # border (2) + at least 4 visible options
_LIST_MAX_VIEWPORT_ROWS = 22


class ModelsPanelDisplayMixin(ModelsPanelDisplayOptionsMixin, _MixinBase):
    """Render rows and handle selection and bucket navigation."""

    if TYPE_CHECKING:
        _active_bucket: str | None
        _bucket_by_name: dict[str, BucketView]
        _changed: bool
        _clock_timer: Any
        _default_effort: str | None
        _effort_snapshot: Any
        _runner_limit_snapshot: Any
        _row_by_id: dict[str, ModelsPanelDisplayRow]
        _top_rows: list[ModelsPanelDisplayRow]
        _updating_highlight: bool
        _views: list[AliasView]
        _warning_toast_emitted: bool
        _override_worker: Any
        _clear_worker: Any
        _provider_routing_changed: bool
        _jump_rendered_row_ids: tuple[str, ...] | None
        _host_visible: bool
        jump_mode_active: bool
        jump_back_stack: list[int]

        @property
        def display_mode(self) -> str: ...

        def jump_hints_by_key(self) -> dict[str, str]: ...

        def invalidate_jump_hints(
            self, *, identities_changed: bool, target_count: int
        ) -> None: ...

        def _load_alias_views(self) -> list[AliasView]: ...

        def _load_default_reasoning_effort(self) -> str | None: ...

        def _start_effort_snapshot_load(self) -> None: ...

        def _refresh_effort_clock(self) -> None: ...

        def _start_runner_limit_snapshot_load(self) -> None: ...

        def _refresh_runner_limit_clock(self) -> None: ...

        def _start_provider_snapshot_load(
            self,
            *,
            keep: str | None = None,
            update_rows: bool = False,
            signal_changes: bool = False,
        ) -> None: ...

        def _refresh_provider_clock(self) -> None: ...

        def _provider_title_text(self) -> Text | None: ...

        def _effort_write_busy(self) -> bool: ...

        def _runner_limit_write_busy(self) -> bool: ...

        def _threshold_write_busy(self) -> bool: ...

        def _provider_write_busy(self) -> bool: ...

        def can_close(self) -> bool: ...

        def _request_close(self) -> None: ...

        def _record_session_cursor(self) -> None: ...

        def _session_preferred_row_id(self) -> str | None: ...

        def _load_models_panel_rows(
            self, views: list[AliasView]
        ) -> list[ModelsPanelDisplayRow]: ...

        def _models_panel_now(self) -> float: ...

    def compose(self) -> ComposeResult:
        options = self._build_options()
        with Container(id="models-panel-container"):
            yield Static(self._title_text(), id="models-panel-title")
            yield OptionList(*options, id="models-panel-list")
            yield Static("", id="models-panel-description")
            yield Static("", id="models-panel-footer")

    def on_mount(self) -> None:
        option_list = self.query_one("#models-panel-list", OptionList)
        if self._host_visible:
            option_list.focus()
        highlighted = option_list.highlighted
        if highlighted is None or self._option_is_disabled(option_list, highlighted):
            self._restore_highlight(option_list, self._session_preferred_row_id())
        self._update_context()
        self._emit_custom_builtin_shadow_warning()
        self._start_effort_snapshot_load()
        self._start_runner_limit_snapshot_load()
        self._start_provider_snapshot_load(update_rows=True)
        self._clock_timer = self.set_interval(5.0, self._refresh_models_clock)

    def _refresh_models_clock(self) -> None:
        """Advance captured countdowns without reading disk or state."""
        if not self._host_visible:
            return
        self._refresh_effort_clock()
        self._refresh_runner_limit_clock()
        self._refresh_provider_clock()

    def _emit_custom_builtin_shadow_warning(self) -> None:
        """Emit the one opening warning derived from the loaded view snapshot."""
        if self._warning_toast_emitted:
            return
        names = sorted(
            view.name for view in self._views if view.is_custom_builtin_shadow
        )
        if not names:
            return
        self._warning_toast_emitted = True
        self.notify(
            custom_builtin_shadow_warning_message(names),
            severity="warning",
        )

    def _footer_markup(self) -> str:
        if self.jump_mode_active:
            action = "back" if self.jump_back_stack else "first"
            return f"JUMP ' {action}  <esc> cancel"
        row = self._selected_row()
        history_hint = _history_footer_hint(row)
        if self._active_bucket is None and isinstance(row, BucketView):
            return (
                "[green]ctrl+e[/green]=Effort  "
                "[green]ctrl+r[/green]=Limit  "
                "[green]p[/green]=Providers  "
                "[green]t[/green]=tmux Agent\n"
                "[green]l/enter[/green]=Open  "
                f"{history_hint}"
                "[dim]j/k[/dim]=Navigate  "
                "[dim]'[/dim]=Jump  "
                "[dim]esc[/dim]=Close"
            )
        if isinstance(row, DefaultEffortSettingRow):
            return (
                "[green]o[/green]=Override  "
                "[green]x[/green]=Clear  "
                "[green]e[/green]=Edit  "
                "[green]r[/green]=Reset  "
                "[green]p[/green]=Providers  "
                "[green]t[/green]=tmux Agent\n"
                "[green]ctrl+e[/green]=Effort  "
                "[dim]j/k[/dim]=Navigate  "
                "[dim]'[/dim]=Jump  "
                "[dim]esc[/dim]=Close"
            )
        if isinstance(row, RunnerLimitSettingRow):
            return (
                "[green]o[/green]=Override  "
                "[green]x[/green]=Clear  "
                "[green]e[/green]=Edit  "
                "[green]p[/green]=Providers  "
                "[green]t[/green]=tmux Agent\n"
                "[green]ctrl+r[/green]=Limit  "
                "[dim]j/k[/dim]=Navigate  "
                "[dim]'[/dim]=Jump  "
                "[dim]esc[/dim]=Close"
            )
        if isinstance(row, BigEpicPhaseThresholdSettingRow):
            return (
                "[green]e/enter[/green]=Edit  "
                "[green]r[/green]=Reset  "
                "[green]p[/green]=Providers  "
                "[green]t[/green]=tmux Agent\n"
                "[green]ctrl+e[/green]=Effort  "
                "[green]ctrl+r[/green]=Limit  "
                "[dim]j/k[/dim]=Navigate  "
                "[dim]'[/dim]=Jump  "
                "[dim]esc[/dim]=Close"
            )
        footer = (
            "[green]ctrl+e[/green]=Effort  "
            "[green]ctrl+r[/green]=Limit  "
            "[green]p[/green]=Providers  "
            "[green]t[/green]=tmux Agent\n"
            "[green]o[/green]=Override  "
            "[green]x[/green]=Clear  "
            "[green]e[/green]=Edit  "
            "[green]r[/green]=Reset"
        )
        if self._active_bucket is not None:
            footer += "  [green]h[/green]=Back"
        footer += f"  {history_hint.rstrip()}" if history_hint else ""
        return footer + (
            "  [dim]j/k[/dim]=Navigate  [dim]'[/dim]=Jump  [dim]esc[/dim]=Close"
        )

    def _title_text(self) -> Text:
        title = (
            "Launch settings" if self.display_mode == "embedded" else "Launch Control"
        )
        text = Text(title, style="bold cyan")
        if self._active_bucket is not None:
            text.append(" › ", style="dim")
            bucket = self._bucket_by_name.get(self._active_bucket)
            if bucket is not None and bucket.is_user_owned:
                text.append("▌ ", style=f"bold {OWNERSHIP_ACCENT}")
                text.append(bucket.name, style=f"bold {OWNERSHIP_ACCENT}")
                text.append(" · custom bucket", style="dim")
            else:
                text.append(self._active_bucket, style="bold #FFD787")
                text.append(" · built-in bucket", style="dim")
        provider_line = self._provider_title_text()
        if provider_line is not None:
            text.append("\n")
            text.append_text(provider_line)
        return text

    def _update_context(self) -> None:
        """Refresh the title, description strip, and context-aware footer."""
        try:
            self.query_one("#models-panel-title", Static).update(self._title_text())
            self.query_one("#models-panel-footer", Static).update(self._footer_markup())
        except Exception:
            pass
        self._update_description_strip()
        self._sync_option_list_viewport()
        self._record_session_cursor()

    def _update_description_strip(self) -> None:
        """Refresh the description strip for the currently highlighted row."""
        try:
            description = self.query_one("#models-panel-description", Static)
        except Exception:
            return
        description.update(
            description_text_for_row(
                self._selected_row(),
                self._default_effort,
                now=self._models_panel_now(),
            )
        )

    def _models_panel_content_width(self) -> int:
        """Return the resolved content width shared by title/list/description/footer."""
        if self.display_mode == "embedded":
            container_width = self.size.width
            try:
                resolved = self.query_one("#models-panel-container").size.width
                if resolved:
                    container_width = resolved
            except Exception:
                pass
            return max(1, int(container_width))
        container_width = min(_MODAL_WIDTH, int(self.size.width * 0.95))
        return max(1, container_width - _MODAL_CHROME_COLS)

    def _sync_option_list_viewport(self) -> None:
        """Shrink the alias list's viewport, never the description or footer.

        The title, description, and footer always render at their intrinsic
        (wrapped) height. When that combined height plus the list's own
        22-row default would exceed the modal's height budget, lower the
        list's max-height just enough to keep everything else fully visible.
        """
        try:
            option_list = self.query_one("#models-panel-list", OptionList)
            title = self.query_one("#models-panel-title", Static)
            description = self.query_one("#models-panel-description", Static)
            footer = self.query_one("#models-panel-footer", Static)
        except Exception:
            return
        width = self._models_panel_content_width()
        empty = Size(0, 0)
        title_rows = title.get_content_height(empty, empty, width)
        description_rows = description.get_content_height(empty, empty, width)
        footer_rows = footer.get_content_height(empty, empty, width)

        title_budget = title_rows + _TITLE_MARGIN_ROWS
        description_budget = _DESCRIPTION_MARGIN_ROWS + max(
            _DESCRIPTION_MIN_BOX_ROWS, 2 + description_rows
        )
        footer_budget = _FOOTER_CHROME_ROWS + footer_rows

        max_height = (
            _MODAL_MAX_HEIGHT_ROWS
            if self.display_mode == "standalone"
            else max(_LIST_MIN_VIEWPORT_ROWS, int(self.size.height))
        )
        chrome_rows = _MODAL_CHROME_ROWS if self.display_mode == "standalone" else 0
        available = (
            max_height - chrome_rows - title_budget - description_budget - footer_budget
        )
        list_cap = max(_LIST_MIN_VIEWPORT_ROWS, min(_LIST_MAX_VIEWPORT_ROWS, available))
        option_list.styles.max_height = list_cap

    def _highlighted_row_id(self) -> str | None:
        option_list = self.query_one("#models-panel-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(highlighted)
        except Exception:
            return None
        return str(option.id) if option.id is not None else None

    def _selected_row(self) -> ModelsPanelDisplayRow | None:
        row_id = self._highlighted_row_id()
        if row_id is None:
            return None
        return self._row_by_id.get(row_id)

    def _selected_alias(self) -> AliasView | None:
        row = self._selected_row()
        if isinstance(row, BucketView):
            self.notify("Press `l`/`enter` to open this bucket")
            return None
        if isinstance(row, AliasView):
            return row
        return None

    def _selected_model_row(self) -> AliasView | LaunchModelSettingRow | None:
        row = self._selected_row()
        if isinstance(row, BucketView):
            self.notify("Press `l`/`enter` to open this bucket")
            return None
        if isinstance(row, (AliasView, LaunchModelSettingRow)):
            return row
        return None

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if self._updating_highlight:
            return
        if event.option is not None and event.option.id is not None:
            row = self._row_by_id.get(str(event.option.id))
            try:
                self.query_one("#models-panel-description", Static).update(
                    description_text_for_row(
                        row,
                        self._default_effort,
                        now=self._models_panel_now(),
                    )
                )
                self.query_one("#models-panel-footer", Static).update(
                    self._footer_markup()
                )
            except Exception:
                pass
            self._sync_option_list_viewport()
            self._record_session_cursor()

    def action_close(self) -> None:
        if not self.can_close():
            return
        self._request_close()

    def action_cancel(self) -> None:
        """Alias for :meth:`action_close` (overrides the navigation mixin)."""
        self.action_close()

    def action_enter_bucket(self) -> None:
        """Drill into the highlighted top-level bucket."""
        if self._active_bucket is not None:
            return
        row = self._selected_row()
        if not isinstance(row, BucketView):
            return
        self._active_bucket = row.name
        first = row.members[0].name if row.members else None
        self._replace_display(keep=first)

    def action_leave_bucket(self) -> None:
        """Return to the top-level rows and restore the source bucket cursor."""
        bucket = self._active_bucket
        if bucket is None:
            return
        self._active_bucket = None
        self._replace_display(keep=f"bucket:{bucket}")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        row = self._selected_row()
        if isinstance(row, BucketView):
            self.action_enter_bucket()
        elif isinstance(row, DefaultEffortSettingRow):
            self.action_manage_default_effort()
        elif isinstance(row, RunnerLimitSettingRow):
            self.action_manage_runner_limit()
        elif isinstance(row, BigEpicPhaseThresholdSettingRow):
            self.action_edit_big_epic_phase_threshold()
        else:
            self.action_override()

    if TYPE_CHECKING:

        def action_override(self) -> None: ...

        def action_manage_default_effort(self) -> None: ...

        def action_manage_runner_limit(self) -> None: ...

        def action_edit_big_epic_phase_threshold(self) -> None: ...


def _history_footer_hint(row: ModelsPanelDisplayRow | None) -> str:
    if isinstance(row, AliasView | BucketView):
        return "[green]H[/green]=History  "
    if isinstance(row, LaunchModelSettingRow) and row.snapshot.referenced_alias:
        return "[green]H[/green]=History  "
    return ""
