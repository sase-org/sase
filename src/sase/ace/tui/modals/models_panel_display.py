"""Display, selection, and bucket navigation for the Models panel."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import OptionList, Static
from textual.widgets._option_list import Option

from sase.llm_provider import (
    AliasView,
    BucketView,
    ModelsPanelSection,
    split_bucket_members,
    split_models_panel_rows,
)

from .models_panel_rendering import (
    OWNERSHIP_ACCENT,
    custom_builtin_shadow_warning_message,
    description_text_for_row,
    panel_value_column_width,
    provider_model_column_width,
    render_bucket_row,
    render_empty_custom_hint,
    render_launch_settings_header,
    render_panel_row,
    render_section_header,
)
from .models_panel_rows import (
    DefaultEffortSettingRow,
    LaunchModelSettingRow,
    ModelsPanelDisplayRow,
    RunnerLimitSettingRow,
)
from .models_panel_types import ModelsPanelResult

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object

_SECTION_ID_PREFIX = "__models-section__:"
_HINT_ID_PREFIX = "__models-hint__:"


class ModelsPanelDisplayMixin(_MixinBase):
    """Render rows and handle selection and bucket navigation."""

    if TYPE_CHECKING:
        _active_bucket: str | None
        _bucket_by_name: dict[str, BucketView]
        _changed: bool
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

        def _provider_write_busy(self) -> bool: ...

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
        option_list.focus()
        highlighted = option_list.highlighted
        if highlighted is None or self._option_is_disabled(option_list, highlighted):
            self._set_highlighted_index(
                option_list, self._first_enabled_option_index(option_list)
            )
        self._update_context()
        self._emit_custom_builtin_shadow_warning()
        self._start_effort_snapshot_load()
        self._start_runner_limit_snapshot_load()
        self._start_provider_snapshot_load(update_rows=True)
        self.set_interval(5.0, self._refresh_models_clock)

    def _refresh_models_clock(self) -> None:
        """Advance captured countdowns without reading disk or state."""
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
        row = self._selected_row()
        if self._active_bucket is None and isinstance(row, BucketView):
            return (
                "[green]ctrl+e[/green]=Effort  "
                "[green]ctrl+r[/green]=Limit  "
                "[green]p[/green]=Providers\n"
                "[green]l/enter[/green]=Open  "
                "[dim]j/k[/dim]=Navigate  "
                "[dim]esc[/dim]=Close"
            )
        if isinstance(row, DefaultEffortSettingRow):
            return (
                "[green]o[/green]=Override  "
                "[green]x[/green]=Clear  "
                "[green]e[/green]=Edit  "
                "[green]r[/green]=Reset  "
                "[green]p[/green]=Providers\n"
                "[green]ctrl+e[/green]=Effort  "
                "[dim]j/k[/dim]=Navigate  "
                "[dim]esc[/dim]=Close"
            )
        if isinstance(row, RunnerLimitSettingRow):
            return (
                "[green]o[/green]=Override  "
                "[green]x[/green]=Clear  "
                "[green]e[/green]=Edit  "
                "[green]p[/green]=Providers\n"
                "[green]ctrl+r[/green]=Limit  "
                "[dim]j/k[/dim]=Navigate  "
                "[dim]esc[/dim]=Close"
            )
        footer = (
            "[green]ctrl+e[/green]=Effort  "
            "[green]ctrl+r[/green]=Limit  "
            "[green]p[/green]=Providers\n"
            "[green]o[/green]=Override  "
            "[green]x[/green]=Clear  "
            "[green]e[/green]=Edit  "
            "[green]r[/green]=Reset"
        )
        if self._active_bucket is not None:
            footer += "  [green]h[/green]=Back"
        return footer + ("  [dim]j/k[/dim]=Navigate  [dim]esc[/dim]=Close")

    def _title_text(self) -> Text:
        text = Text("Models", style="bold cyan")
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

    def _build_options(self) -> list[Option]:
        self._top_rows = self._load_models_panel_rows(self._views)
        self._sync_bucket_index()
        return self._render_current_options()

    def _sync_bucket_index(self) -> None:
        """Refresh bucket lookup from the current top-level rows."""
        self._bucket_by_name = {
            row.name: row for row in self._top_rows if isinstance(row, BucketView)
        }
        if (
            self._active_bucket is not None
            and self._active_bucket not in self._bucket_by_name
        ):
            self._active_bucket = None

    @staticmethod
    def _row_id(row: ModelsPanelDisplayRow) -> str:
        if isinstance(
            row, (LaunchModelSettingRow, DefaultEffortSettingRow, RunnerLimitSettingRow)
        ):
            return row.row_id
        if isinstance(row, BucketView):
            return f"bucket:{row.name}"
        return row.name

    def _current_rows(self) -> list[ModelsPanelDisplayRow]:
        if self._active_bucket is None:
            return self._top_rows
        bucket = self._bucket_by_name.get(self._active_bucket)
        return list(bucket.members) if bucket is not None else []

    def _current_sections(
        self, rows: list[AliasView | BucketView] | list[AliasView]
    ) -> tuple[tuple[ModelsPanelSection, ...], bool]:
        """Return current ownership sections and whether to show their headers."""
        if self._active_bucket is None:
            builtin, user = split_models_panel_rows(rows)
            return (builtin, user), True
        bucket = self._bucket_by_name.get(self._active_bucket)
        if bucket is None:
            return (), False
        builtin, user = split_bucket_members(bucket)
        if builtin.rows and user.rows:
            return (builtin, user), True
        return ((builtin,) if builtin.rows else (user,)), False

    def _render_current_options(self) -> list[Option]:
        rows = self._current_rows()
        now = self._models_panel_now()
        self._row_by_id = {self._row_id(row): row for row in rows}
        options: list[Option] = []
        if self._active_bucket is None:
            launch_rows = [
                row
                for row in rows
                if isinstance(
                    row,
                    (
                        LaunchModelSettingRow,
                        DefaultEffortSettingRow,
                        RunnerLimitSettingRow,
                    ),
                )
            ]
            model_rows = [
                row for row in rows if isinstance(row, (AliasView, BucketView))
            ]
            value_width = panel_value_column_width(rows, now=now)
            if launch_rows:
                options.append(
                    Option(
                        render_launch_settings_header(
                            value_width=value_width,
                            count=len(launch_rows),
                        ),
                        id=f"{_SECTION_ID_PREFIX}launch",
                        disabled=True,
                    )
                )
                for row in launch_rows:
                    options.append(
                        Option(
                            render_panel_row(row, now=now, value_width=value_width),
                            id=self._row_id(row),
                        )
                    )
            sections, show_headers = self._current_sections(model_rows)
            provider_model_width = value_width
        else:
            alias_rows = [row for row in rows if isinstance(row, AliasView)]
            provider_model_width = provider_model_column_width(alias_rows)
            sections, show_headers = self._current_sections(alias_rows)
        for section in sections:
            if show_headers:
                options.append(
                    Option(
                        render_section_header(
                            section,
                            provider_model_width=provider_model_width,
                        ),
                        id=f"{_SECTION_ID_PREFIX}{section.ownership}",
                        disabled=True,
                    )
                )
            for section_row in cast("tuple[AliasView | BucketView, ...]", section.rows):
                row_id = self._row_id(section_row)
                if isinstance(section_row, BucketView):
                    prompt = render_bucket_row(
                        section_row, provider_model_width=provider_model_width
                    )
                else:
                    prompt = render_panel_row(
                        section_row, now=now, value_width=provider_model_width
                    )
                options.append(Option(prompt, id=row_id))
            if (
                show_headers
                and self._active_bucket is None
                and section.is_user_owned
                and not section.rows
            ):
                options.append(
                    Option(
                        render_empty_custom_hint(),
                        id=f"{_HINT_ID_PREFIX}empty-custom",
                        disabled=True,
                    )
                )
        return options

    @staticmethod
    def _option_is_disabled(option_list: OptionList, index: int) -> bool:
        """Return whether the option at *index* is disabled."""
        try:
            return option_list.get_option_at_index(index).disabled
        except Exception:
            return True

    @classmethod
    def _first_enabled_option_index(cls, option_list: OptionList) -> int | None:
        """Return the first actionable option index, if one exists."""
        for index in range(option_list.option_count):
            if not cls._option_is_disabled(option_list, index):
                return index
        return None

    def _set_highlighted_index(
        self, option_list: OptionList, index: int | None
    ) -> None:
        self._updating_highlight = True
        try:
            option_list.highlighted = index
        finally:
            self._updating_highlight = False

    def _replace_display(self, *, keep: str | None = None) -> None:
        option_list = self.query_one("#models-panel-list", OptionList)
        self._sync_bucket_index()
        option_list.clear_options()
        option_list.add_options(self._render_current_options())
        self._restore_highlight(option_list, keep)
        self._update_context()

    def _restore_highlight(
        self, option_list: OptionList, preferred: str | None
    ) -> None:
        if preferred is not None:
            try:
                index = option_list.get_option_index(preferred)
                if not self._option_is_disabled(option_list, index):
                    self._set_highlighted_index(option_list, index)
                    return
            except Exception:
                pass
        self._set_highlighted_index(
            option_list, self._first_enabled_option_index(option_list)
        )

    def _moved_highlight_row_id(self) -> str | None:
        """Return the current row only when the user has left the first row.

        First paint has no launch-setting rows, so the implicit cursor sits on
        ``setting:default_effort``. A later snapshot should then land on the
        new first launch row. A user-moved cursor must stay put.
        """
        option_list = self.query_one("#models-panel-list", OptionList)
        current = self._highlighted_row_id()
        if current is None:
            return None
        first_index = self._first_enabled_option_index(option_list)
        if first_index is None:
            return current
        try:
            first_option = option_list.get_option_at_index(first_index)
        except Exception:
            return current
        first_id = str(first_option.id) if first_option.id is not None else None
        return current if current != first_id else None

    def _refresh_rows(self, *, keep: str | None = None) -> None:
        """Reload and rebuild rows, preserving the highlighted row when possible."""
        preferred = keep or self._highlighted_row_id()
        self._start_provider_snapshot_load(
            keep=preferred,
            update_rows=True,
            signal_changes=True,
        )

    def _update_context(self) -> None:
        """Refresh the title, description strip, and context-aware footer."""
        try:
            self.query_one("#models-panel-title", Static).update(self._title_text())
            self.query_one("#models-panel-footer", Static).update(self._footer_markup())
        except Exception:
            pass
        self._update_description_strip()

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

    def action_close(self) -> None:
        if (
            self._override_worker is not None
            or self._clear_worker is not None
            or self._effort_write_busy()
            or self._runner_limit_write_busy()
            or self._provider_write_busy()
        ):
            self.notify("An override update is still in progress.", severity="warning")
            return
        self.dismiss(
            ModelsPanelResult(
                changed=self._changed,
                provider_routing_changed=self._provider_routing_changed,
            )
        )

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
        else:
            self.action_override()

    if TYPE_CHECKING:

        def action_override(self) -> None: ...

        def action_manage_default_effort(self) -> None: ...

        def action_manage_runner_limit(self) -> None: ...
