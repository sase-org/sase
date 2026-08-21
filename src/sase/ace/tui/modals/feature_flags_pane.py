"""Config hub Flags pane: inspect and persist feature-flag preferences."""

from __future__ import annotations

from datetime import date

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from rich.text import Text
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.ace.tui.update_restart import restart_after_update_when_ready
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.selection import (
    ProgrammaticSelectionGuard,
    restore_selection_by_identity,
)
from sase.feature_flags.cli_views import FlagView
from sase.feature_flags.models import (
    FeatureFlagDiagnostic,
    FeatureFlagError,
    FeatureFlagStateError,
)
from sase.feature_flags.state import set_saved_feature_flag

from .base import CopyModeForwardingMixin, FilterInput
from .catalog_pane_contract import CatalogPaneHost, CatalogPaneSession
from .confirm_action_modal import ConfirmActionModal
from .feature_flags_pane_load import (
    FeatureFlagsPaneLoad,
    load_feature_flags_pane_state,
)
from .feature_flags_pane_rendering import (
    FLAGS_PANE_ACCENT,
    build_corrupt_state_message,
    build_detail_description,
    build_detail_meta,
    build_detail_title,
    build_empty_catalog_message,
    build_error_message,
    build_flag_row_text,
    build_loading_card,
    build_no_match_message,
    build_panel_footer,
    build_panel_header,
    build_toggle_confirmation,
    filter_flag_views,
    flag_rail_width,
)

_LIST_ID = "feature-flags-pane-list"
_FILTER_ID = "feature-flags-pane-filter"
_RESTART_PURPOSE = "apply feature-flag changes"
_RESTART_MESSAGE = "Feature-flag changes saved"


class _FlagsFilterInput(FilterInput):
    """The pane's inline filter box; Escape closes it without cancelling ACE."""

    BINDINGS = [*FilterInput.BINDINGS, ("escape", "close_filter", "Close filter")]

    def on_key(self, event: events.Key) -> None:
        from .config_hub_keys import handle_config_hub_bracket_key

        handle_config_hub_bracket_key(self, event)

    def action_close_filter(self) -> None:
        pane = self._pane()
        if pane is not None:
            pane._close_filter(clear=True)

    def _pane(self) -> FeatureFlagsPane | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, FeatureFlagsPane):
                return node
            node = getattr(node, "parent", None)
        return None


class FeatureFlagsPane(CopyModeForwardingMixin, Vertical):
    """Browse registered feature flags and persist enable/disable choices."""

    can_focus = False
    BINDINGS = [
        ("slash", "filter_flags", "Filter"),
        ("r", "refresh", "Refresh"),
        ("space", "toggle_flag", "Toggle"),
        ("j", "next_flag", "Next"),
        ("k", "prev_flag", "Previous"),
        ("down", "next_flag", "Next"),
        ("up", "prev_flag", "Previous"),
        ("home", "first_flag", "First"),
        ("end", "last_flag", "Last"),
        ("escape", "escape", "Close"),
        ("q", "close", "Close"),
    ]

    def __init__(
        self,
        *,
        host: CatalogPaneHost | None = None,
        session: CatalogPaneSession | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._host = host
        self._session = session
        self._host_visible = True
        self._accent = FLAGS_PANE_ACCENT
        self._all_views: tuple[FlagView, ...] = ()
        self._views: tuple[FlagView, ...] = ()
        self._current_key: str | None = None
        self._filter_text = ""
        self._loading = True
        self._error: str | None = None
        self._state_path = ""
        self._diagnostics: tuple[FeatureFlagDiagnostic, ...] = ()
        self._today: date | None = None
        self._release = ""
        self._load_generation = 0
        self._load_worker: Worker[tuple[int, FeatureFlagsPaneLoad]] | None = None
        self._mutate_worker: Worker[str | None] | None = None
        self._mutating = False
        self._confirm_open = False
        self._selection_guard = ProgrammaticSelectionGuard()
        self._debouncer: DetailPanelDebouncer | None = None

    def compose(self) -> ComposeResult:
        with Container(id="feature-flags-pane-container"):
            yield Static(self._loading_header(), id="feature-flags-pane-header")
            with Horizontal(id="feature-flags-pane-body"):
                yield OptionList(id=_LIST_ID)
                with VerticalScroll(id="feature-flags-pane-detail"):
                    yield Static("", id="feature-flags-pane-card-title")
                    yield Static("", id="feature-flags-pane-card-description")
                    yield Static("", id="feature-flags-pane-card-meta")
            yield _FlagsFilterInput(
                placeholder="Filter key, description, kind, state, provenance…",
                id=_FILTER_ID,
            )
            yield Static("", id="feature-flags-pane-footer")

    def on_mount(self) -> None:
        self._debouncer = DetailPanelDebouncer(self.app)
        self._filter_input().display = False
        self.query_one("#feature-flags-pane-detail", VerticalScroll).can_focus = False
        self.focus_default()
        self._start_load()

    def on_unmount(self) -> None:
        if self._debouncer is not None:
            self._debouncer.cancel()
        for worker in (self._load_worker, self._mutate_worker):
            if worker is not None and not worker.is_finished:
                worker.cancel()

    def on_resize(self, _event: events.Resize) -> None:
        self._resize_flag_rail()

    def on_key(self, event: events.Key) -> None:
        from .config_hub_keys import handle_config_hub_subtab_select_key

        if handle_config_hub_subtab_select_key(self, event):
            return
        super().on_key(event)

    def focus_default(self) -> None:
        """Focus the flag list when this pane is the active surface."""
        if not self._host_visible:
            return
        try:
            target = (
                self._filter_input()
                if self._filter_input().display
                else self._flag_list()
            )
            self.app.set_focus(target)
        except Exception:
            pass

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        """Pause focus and pending card paints while another tab is showing."""
        self._host_visible = active
        if active:
            self._render_detail_card()
            self._update_header()
            self._update_footer()
            self.focus_default()
            return
        if self._debouncer is not None:
            self._debouncer.cancel()

    def action_close(self) -> None:
        if self._host is not None:
            self._host.request_close()

    def action_escape(self) -> None:
        filter_input = self._filter_input()
        if filter_input.display:
            self._close_filter(clear=True)
            return
        if self._filter_text:
            self._apply_filter("")
            return
        self.action_close()

    def action_filter_flags(self) -> None:
        filter_input = self._filter_input()
        filter_input.display = True
        filter_input.value = self._filter_text
        filter_input.focus()
        self._update_footer()

    def action_refresh(self) -> None:
        if self._mutating:
            return
        self._start_load()

    def action_next_flag(self) -> None:
        if self._views:
            self._flag_list().action_cursor_down()

    def action_prev_flag(self) -> None:
        if self._views:
            self._flag_list().action_cursor_up()

    def action_first_flag(self) -> None:
        if self._views:
            self._flag_list().highlighted = 0

    def action_last_flag(self) -> None:
        if self._views:
            self._flag_list().highlighted = len(self._views) - 1

    def action_toggle_flag(self) -> None:
        self._request_toggle()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != _FILTER_ID:
            return
        self._apply_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != _FILTER_ID:
            return
        self._close_filter(clear=False)

    @on(OptionList.OptionSelected, f"#{_LIST_ID}")
    def _on_flag_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self._request_toggle()

    @on(OptionList.OptionHighlighted, f"#{_LIST_ID}")
    def _on_flag_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        idx = event.option_index
        if not 0 <= idx < len(self._views):
            return
        current_idx = self._current_row()
        if not 0 <= current_idx < len(self._views):
            return
        identity = str(self._views[idx].definition.key)
        current_identity = str(self._views[current_idx].definition.key)
        if self._selection_guard.should_ignore(
            identity,
            idx,
            current_identity=current_identity,
            current_row=current_idx,
        ):
            return
        self._current_key = identity
        self._record_session_selection()
        self._update_footer()
        if self._debouncer is not None:
            self._debouncer.schedule(self._render_detail_card)
        else:
            self._render_detail_card()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._load_worker:
            self._on_load_state_changed(event)
        elif event.worker is self._mutate_worker:
            self._on_mutate_state_changed(event)

    def _start_load(self) -> None:
        self._loading = True
        self._error = None
        self._update_header()
        self._render_detail_card()
        self._update_footer()
        self._load_generation += 1
        generation = self._load_generation

        def task() -> tuple[int, FeatureFlagsPaneLoad]:
            return generation, load_feature_flags_pane_state()

        self._load_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="feature-flags-load",
        )

    def _on_load_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state not in {WorkerState.SUCCESS, WorkerState.ERROR}:
            return
        if event.state == WorkerState.ERROR:
            self._loading = False
            self._error = "Feature-flag load failed."
            self._all_views = ()
            self._apply_filter(self._filter_text, preferred_key=self._current_key)
            self.focus_default()
            return
        result = event.worker.result
        if not isinstance(result, tuple) or len(result) != 2:
            return
        generation, payload = result
        if generation != self._load_generation:
            return
        if not isinstance(payload, FeatureFlagsPaneLoad):
            return
        self._loading = False
        self._error = payload.error
        self._state_path = payload.state_path
        self._diagnostics = payload.diagnostics
        self._today = payload.today
        self._release = payload.release
        self._all_views = payload.views
        preferred = self._preferred_key()
        self._apply_filter(self._filter_text, preferred_key=preferred)
        self.focus_default()

    def _preferred_key(self) -> str | None:
        if self._current_key is not None:
            return self._current_key
        if self._session is not None:
            return self._session.entry_id
        return None

    def _apply_filter(
        self,
        pattern: str,
        *,
        preferred_key: str | None = None,
    ) -> None:
        self._filter_text = pattern
        preferred = preferred_key if preferred_key is not None else self._current_key
        views = filter_flag_views(self._all_views, pattern)
        self._set_views(views, preferred_key=preferred)
        self._update_header()
        self._update_footer()

    def _set_views(
        self, views: tuple[FlagView, ...], *, preferred_key: str | None
    ) -> None:
        option_list = self._flag_list()
        prior_row = self._current_row()
        row = restore_selection_by_identity(
            views,
            prior_identity=preferred_key,
            prior_visual_row=prior_row,
            identity_fn=lambda view: str(view.definition.key),
        )
        self._views = views
        self._selection_guard.clear()
        option_list.clear_options()
        option_list.add_options(
            Option(
                build_flag_row_text(view),
                id=str(view.definition.key),
            )
            for view in views
        )
        if views:
            identity = str(views[row].definition.key)
            self._selection_guard.prepare(identity, row)
            option_list.highlighted = row
            self._current_key = identity
        else:
            self._current_key = None
        self._record_session_selection()
        self._resize_flag_rail()
        self._render_detail_card()

    def _record_session_selection(self) -> None:
        if self._session is not None:
            self._session.record_entry(self._current_key)

    def _flag_list(self) -> OptionList:
        return self.query_one(f"#{_LIST_ID}", OptionList)

    def _filter_input(self) -> FilterInput:
        return self.query_one(f"#{_FILTER_ID}", FilterInput)

    def _current_row(self) -> int:
        option_list = self._flag_list()
        if option_list.highlighted is None:
            return 0
        return max(0, min(option_list.highlighted, max(0, len(self._views) - 1)))

    def _selected_view(self) -> FlagView | None:
        if not self._views:
            return None
        row = self._current_row()
        if not 0 <= row < len(self._views):
            return None
        return self._views[row]

    def _close_filter(self, *, clear: bool) -> None:
        filter_input = self._filter_input()
        filter_input.display = False
        if clear and self._filter_text:
            filter_input.value = ""
            self._apply_filter("")
        if self._host_visible:
            self.app.set_focus(self._flag_list())
        self._update_footer()

    def _loading_header(self) -> Text:
        return build_panel_header((), loading=True, accent=self._accent)

    def _update_header(self) -> None:
        header = build_panel_header(
            self._all_views,
            loading=self._loading,
            error=self._error,
            accent=self._accent,
        )
        self.query_one("#feature-flags-pane-header", Static).update(header)

    def _update_footer(self) -> None:
        footer = build_panel_footer(
            filter_open=self._filter_input().display,
            has_selection=self._selected_view() is not None,
            mutating=self._mutating,
        )
        self.query_one("#feature-flags-pane-footer", Static).update(footer)

    def _resize_flag_rail(self) -> None:
        try:
            body = self.query_one("#feature-flags-pane-body", Horizontal)
            flag_list = self._flag_list()
        except NoMatches:
            return
        width = flag_rail_width(self._all_views, available_width=body.size.width)
        current = flag_list.styles.width
        if current is not None and current.is_cells and int(current.value) == width:
            return
        flag_list.styles.width = width

    def _render_detail_card(self) -> None:
        title_widget = self.query_one("#feature-flags-pane-card-title", Static)
        description_widget = self.query_one(
            "#feature-flags-pane-card-description", Static
        )
        meta_widget = self.query_one("#feature-flags-pane-card-meta", Static)
        if self._loading:
            title, description, meta = build_loading_card()
            title_widget.update(title)
            description_widget.update(description)
            meta_widget.update(meta)
            return
        if self._error:
            title_widget.update("")
            description_widget.update(build_error_message(self._error))
            meta_widget.update("")
            return
        if self._has_corrupt_state() and not self._all_views:
            title_widget.update("")
            description_widget.update(build_corrupt_state_message(self._diagnostics))
            meta_widget.update("")
            return
        if not self._all_views:
            title_widget.update("")
            description_widget.update(build_empty_catalog_message())
            meta_widget.update("")
            return
        if not self._views:
            title_widget.update("")
            description_widget.update(build_no_match_message(self._filter_text))
            meta_widget.update("")
            return
        view = self._selected_view()
        if view is None:
            title_widget.update("")
            description_widget.update(build_empty_catalog_message())
            meta_widget.update("")
            return
        title_widget.update(build_detail_title(view))
        description_widget.update(build_detail_description(view))
        meta_widget.update(
            build_detail_meta(
                view,
                state_path=self._state_path,
                diagnostics=self._diagnostics,
                today=self._today,
                release=self._release,
            )
        )

    def _has_corrupt_state(self) -> bool:
        return any(
            getattr(diagnostic, "severity", "") == "error"
            for diagnostic in self._diagnostics
        )

    def _request_toggle(self) -> None:
        if self._mutating or self._confirm_open or self._loading:
            return
        view = self._selected_view()
        if view is None:
            return
        copy = build_toggle_confirmation(view, state_path=self._state_path)
        modal = ConfirmActionModal(
            copy.title,
            copy.message,
            subject=copy.subject,
            default="cancel",
            confirm_label="Save and restart",
            cancel_label="Cancel",
        )
        self._confirm_open = True

        def on_dismiss(confirmed: bool | None) -> None:
            self._confirm_open = False
            if confirmed:
                self._start_mutation(view)

        self.app.push_screen(modal, on_dismiss)

    def _start_mutation(self, view: FlagView) -> None:
        if self._mutating:
            return
        self._mutating = True
        self._update_footer()
        target = not view.decision.enabled
        key = str(view.definition.key)

        def task() -> str | None:
            try:
                set_saved_feature_flag(key, target)
            except (FeatureFlagError, FeatureFlagStateError) as exc:
                return str(exc) or type(exc).__name__
            except Exception as exc:
                return str(exc) or type(exc).__name__
            return None

        self._mutate_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="feature-flags-mutate",
        )

    def _on_mutate_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state not in {WorkerState.SUCCESS, WorkerState.ERROR}:
            return
        if not self.is_mounted:
            return
        self._mutating = False
        self._update_footer()
        if event.state == WorkerState.ERROR:
            error = event.worker.error
            self._notify_error(str(error) if error else "Could not save feature flag.")
            return
        result = event.worker.result
        if isinstance(result, str) and result:
            self._notify_error(result)
            return
        restart_after_update_when_ready(
            self.app,
            _RESTART_MESSAGE,
            deferred=False,
            restart_purpose=_RESTART_PURPOSE,
        )

    def _notify_error(self, message: str) -> None:
        notify = getattr(self.app, "notify", None)
        if callable(notify):
            notify(message, severity="error")


__all__ = ["FeatureFlagsPane"]
