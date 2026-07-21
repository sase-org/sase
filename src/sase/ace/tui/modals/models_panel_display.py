"""Display, selection, and bucket navigation for the Models panel."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import OptionList, Static
from textual.widgets._option_list import Option

from sase.llm_provider import AliasView, BucketView

from .models_panel_rendering import (
    custom_builtin_shadow_warning_message,
    description_text_for_row,
    provider_model_column_width,
    render_alias_row,
    render_bucket_row,
)
from .models_panel_types import ModelsPanelResult

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


class ModelsPanelDisplayMixin(_MixinBase):
    """Render rows and handle selection and bucket navigation."""

    if TYPE_CHECKING:
        _active_bucket: str | None
        _bucket_by_name: dict[str, BucketView]
        _changed: bool
        _default_effort: str | None
        _row_by_id: dict[str, AliasView | BucketView]
        _top_rows: list[AliasView | BucketView]
        _updating_highlight: bool
        _views: list[AliasView]
        _warning_toast_emitted: bool
        _override_worker: Any
        _clear_worker: Any

        def _load_alias_views(self) -> list[AliasView]: ...

        def _load_default_reasoning_effort(self) -> str | None: ...

        def _load_models_panel_rows(
            self, views: list[AliasView]
        ) -> list[AliasView | BucketView]: ...

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
        if option_list.option_count and option_list.highlighted is None:
            self._set_highlighted_index(option_list, 0)
        self._update_context()
        self._emit_custom_builtin_shadow_warning()

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
                "[green]l/enter[/green]=Open  "
                "[dim]j/k[/dim]=Navigate  "
                "[dim]esc[/dim]=Close"
            )
        footer = (
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
            text.append(self._active_bucket, style="bold #FFD787")
        text.append("\n")
        text.append("default effort: ", style="dim #878787")
        if self._default_effort is None:
            text.append("provider default", style="dim #878787")
        else:
            text.append("@ ", style="#878787")
            text.append(self._default_effort, style="bold #AF87FF")
        return text

    def _build_options(self) -> list[Option]:
        self._default_effort = self._load_default_reasoning_effort()
        self._views = self._load_alias_views()
        self._top_rows = self._load_models_panel_rows(self._views)
        self._bucket_by_name = {
            row.name: row for row in self._top_rows if isinstance(row, BucketView)
        }
        if (
            self._active_bucket is not None
            and self._active_bucket not in self._bucket_by_name
        ):
            self._active_bucket = None
        return self._render_current_options()

    @staticmethod
    def _row_id(row: AliasView | BucketView) -> str:
        if isinstance(row, BucketView):
            return f"bucket:{row.name}"
        return row.name

    def _current_rows(self) -> list[AliasView | BucketView]:
        if self._active_bucket is None:
            return self._top_rows
        bucket = self._bucket_by_name.get(self._active_bucket)
        return list(bucket.members) if bucket is not None else []

    def _render_current_options(self) -> list[Option]:
        rows = self._current_rows()
        alias_rows = [row for row in rows if isinstance(row, AliasView)]
        provider_model_width = provider_model_column_width(alias_rows)
        now = self._models_panel_now()
        self._row_by_id = {self._row_id(row): row for row in rows}
        options: list[Option] = []
        for row in rows:
            row_id = self._row_id(row)
            if isinstance(row, BucketView):
                prompt = render_bucket_row(
                    row, provider_model_width=provider_model_width
                )
            else:
                prompt = render_alias_row(
                    row, now=now, provider_model_width=provider_model_width
                )
            options.append(Option(prompt, id=row_id))
        return options

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
                self._set_highlighted_index(option_list, index)
                return
            except Exception:
                pass
        self._set_highlighted_index(
            option_list, 0 if option_list.option_count else None
        )

    def _refresh_rows(self, *, keep: str | None = None) -> None:
        """Reload and rebuild rows, preserving the highlighted row when possible."""
        option_list = self.query_one("#models-panel-list", OptionList)
        preferred = keep or self._highlighted_row_id()
        option_list.clear_options()
        option_list.add_options(self._build_options())
        self._restore_highlight(option_list, preferred)
        self._update_context()

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
            description_text_for_row(self._selected_row(), self._default_effort)
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

    def _selected_row(self) -> AliasView | BucketView | None:
        row_id = self._highlighted_row_id()
        if row_id is None:
            return None
        return self._row_by_id.get(row_id)

    def _selected_alias(self) -> AliasView | None:
        row = self._selected_row()
        if isinstance(row, BucketView):
            self.notify("Press `l`/`enter` to open this bucket")
            return None
        return row

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if self._updating_highlight:
            return
        if event.option is not None and event.option.id is not None:
            row = self._row_by_id.get(str(event.option.id))
            try:
                self.query_one("#models-panel-description", Static).update(
                    description_text_for_row(row, self._default_effort)
                )
                self.query_one("#models-panel-footer", Static).update(
                    self._footer_markup()
                )
            except Exception:
                pass

    def action_close(self) -> None:
        if self._override_worker is not None or self._clear_worker is not None:
            self.notify("An override update is still in progress.", severity="warning")
            return
        self.dismiss(ModelsPanelResult(changed=self._changed))

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
        if isinstance(self._selected_row(), BucketView):
            self.action_enter_bucket()
        else:
            self.action_override()

    if TYPE_CHECKING:

        def action_override(self) -> None: ...
