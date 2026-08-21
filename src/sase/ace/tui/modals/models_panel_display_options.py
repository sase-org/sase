"""Build and refresh the option list shown by the Models panel."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, overload

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets._option_list import Option

from sase.llm_provider import (
    AliasView,
    BucketView,
    ModelsPanelSection,
    split_bucket_members,
    split_models_panel_rows,
)

from .models_panel_rendering import (
    PROVIDER_MODEL_CELL_MAX,
    apply_jump_gutter,
    jump_hint_gutter_width,
    panel_value_column_width,
    provider_model_column_width,
    render_bucket_row,
    render_empty_custom_hint,
    render_launch_settings_header,
    render_panel_row,
    render_section_header,
    render_section_spacer,
)
from .models_panel_rows import (
    BigEpicPhaseThresholdSettingRow,
    DefaultEffortSettingRow,
    LaunchModelSettingRow,
    ModelsPanelDisplayRow,
    RunnerLimitSettingRow,
)

if TYPE_CHECKING:
    from textual.css.query import QueryType
    from textual.widget import Widget

_SECTION_ID_PREFIX = "__models-section__:"
_HINT_ID_PREFIX = "__models-hint__:"
_SPACER_ID_PREFIX = "__models-spacer__:"


class ModelsPanelDisplayOptionsMixin:
    """Own option construction, repainting, and highlight restoration."""

    if TYPE_CHECKING:
        _active_bucket: str | None
        _bucket_by_name: dict[str, BucketView]
        _hidden_refresh_pending: bool
        _host_visible: bool
        _jump_rendered_row_ids: tuple[str, ...] | None
        _row_by_id: dict[str, ModelsPanelDisplayRow]
        _top_rows: list[ModelsPanelDisplayRow]
        _updating_highlight: bool
        _views: list[AliasView]
        jump_mode_active: bool

        @overload
        def query_one(self, selector: str) -> Widget: ...

        @overload
        def query_one(self, selector: type[QueryType]) -> QueryType: ...

        @overload
        def query_one(
            self, selector: str, expect_type: type[QueryType]
        ) -> QueryType: ...

        def query_one(
            self,
            selector: str | type[QueryType],
            expect_type: type[QueryType] | None = None,
        ) -> QueryType | Widget: ...

        def jump_hints_by_key(self) -> dict[str, str]: ...

        def invalidate_jump_hints(
            self, *, identities_changed: bool, target_count: int
        ) -> None: ...

        def _highlighted_row_id(self) -> str | None: ...

        def _load_models_panel_rows(
            self, views: list[AliasView]
        ) -> list[ModelsPanelDisplayRow]: ...

        def _models_panel_now(self) -> float: ...

        def _start_provider_snapshot_load(
            self,
            *,
            keep: str | None = None,
            update_rows: bool = False,
            signal_changes: bool = False,
        ) -> None: ...

        def _update_context(self) -> None: ...

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
            row,
            (
                LaunchModelSettingRow,
                DefaultEffortSettingRow,
                RunnerLimitSettingRow,
                BigEpicPhaseThresholdSettingRow,
            ),
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

    def _sync_jump_target_identity(self) -> None:
        """Invalidate stale jump hints/history before this row set is painted.

        Compares the ids about to be rendered against the ids from the last
        rendered list -- across bucket entry/exit, async provider-snapshot
        reloads, and alias/config edits alike -- so a changed or reordered
        set clears painted hints and the back stack, while an unchanged set
        only drops hints that now point past the row count. That keeps
        value-only rebuilds (countdown ticks, provenance-chip updates) from
        disturbing an open jump session. The tuple is only recorded, not
        compared, on first composition so no history is manufactured before
        the user has ever pressed ``'``.
        """
        next_ids = tuple(self._row_by_id)
        previous_ids = self._jump_rendered_row_ids
        self._jump_rendered_row_ids = next_ids
        if previous_ids is None:
            return
        self.invalidate_jump_hints(
            identities_changed=next_ids != previous_ids,
            target_count=len(next_ids),
        )

    def _render_current_options(self) -> list[Option]:
        rows = self._current_rows()
        now = self._models_panel_now()
        self._row_by_id = {self._row_id(row): row for row in rows}
        self._sync_jump_target_identity()
        jump_mode = self.jump_mode_active
        jump_hints = self.jump_hints_by_key() if jump_mode else {}
        gutter_width = jump_hint_gutter_width(len(jump_hints)) if jump_mode else 0
        cap = (
            PROVIDER_MODEL_CELL_MAX - gutter_width
            if jump_mode
            else (PROVIDER_MODEL_CELL_MAX)
        )

        def _decorate(prompt: Text, row_id: str) -> Text:
            if not jump_mode:
                return prompt
            return apply_jump_gutter(
                prompt, jump_hints.get(row_id), gutter_width=gutter_width
            )

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
                        BigEpicPhaseThresholdSettingRow,
                    ),
                )
            ]
            model_rows = [
                row for row in rows if isinstance(row, (AliasView, BucketView))
            ]
            value_width = panel_value_column_width(rows, now=now, cap=cap)
            if launch_rows:
                launch_header_id = f"{_SECTION_ID_PREFIX}launch"
                options.append(
                    Option(
                        _decorate(
                            render_launch_settings_header(
                                value_width=value_width,
                                count=len(launch_rows),
                            ),
                            launch_header_id,
                        ),
                        id=launch_header_id,
                        disabled=True,
                    )
                )
                for row in launch_rows:
                    row_id = self._row_id(row)
                    options.append(
                        Option(
                            _decorate(
                                render_panel_row(row, now=now, value_width=value_width),
                                row_id,
                            ),
                            id=row_id,
                        )
                    )
            sections, show_headers = self._current_sections(model_rows)
            provider_model_width = value_width
        else:
            alias_rows = [row for row in rows if isinstance(row, AliasView)]
            provider_model_width = provider_model_column_width(alias_rows, cap=cap)
            sections, show_headers = self._current_sections(alias_rows)
        visible_section_index = 0 if options else -1
        for section in sections:
            section_visible = bool(section.rows) or (
                self._active_bucket is None and section.is_user_owned
            )
            if not section_visible:
                continue
            if options and visible_section_index >= 0:
                spacer_id = (
                    f"{_SPACER_ID_PREFIX}"
                    f"{self._active_bucket or 'top'}:{section.ownership}"
                )
                options.append(
                    Option(
                        _decorate(render_section_spacer(), spacer_id),
                        id=spacer_id,
                        disabled=True,
                    )
                )
            visible_section_index += 1
            if show_headers:
                section_header_id = f"{_SECTION_ID_PREFIX}{section.ownership}"
                options.append(
                    Option(
                        _decorate(
                            render_section_header(
                                section,
                                provider_model_width=provider_model_width,
                            ),
                            section_header_id,
                        ),
                        id=section_header_id,
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
                options.append(Option(_decorate(prompt, row_id), id=row_id))
            if (
                show_headers
                and self._active_bucket is None
                and section.is_user_owned
                and not section.rows
            ):
                empty_hint_id = f"{_HINT_ID_PREFIX}empty-custom"
                options.append(
                    Option(
                        _decorate(render_empty_custom_hint(), empty_hint_id),
                        id=empty_hint_id,
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
        if not self._host_visible:
            self._hidden_refresh_pending = True
            return
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


__all__ = ["ModelsPanelDisplayOptionsMixin"]
