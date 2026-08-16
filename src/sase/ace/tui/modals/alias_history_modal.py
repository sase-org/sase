"""The Launch Control alias-history panel (``H``).

Shows bounded prior runs for one alias or every member of a collapsed
bucket. Every load and re-query (initial open, ``Ctrl+K`` load-more, ``r``
revalidate, ``.`` hidden-toggle) runs through one worker-backed seam so no
query, filesystem read, or parsing ever runs on the UI thread. The modal
never mutates the Launch Control panel that opened it.
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets._option_list import Option
from textual.worker import Worker, WorkerState

from sase.artifact_refs import reference_for_agent_name
from sase.llm_provider.alias_history import (
    AliasHistoryRun,
    AliasHistoryView,
    load_alias_history,
)
from sase.llm_provider.config import get_model_alias_history_limit

from ..actions.clipboard import schedule_copy_delivery
from ..actions.navigation.jump_hints import normalize_jump_key
from ..widgets._prompt_preview_target import PreviewPayload
from .alias_history_rendering import (
    alias_history_detail_text,
    alias_history_footer_markup,
    alias_history_title_text,
    build_alias_history_rows,
)
from .alias_history_state import (
    AliasHistoryEntryRequest,
    AliasHistoryLoadRequest,
    alias_history_run_key,
    doubled_alias_history_limit,
    initial_alias_history_load_request,
)
from .base import OptionListNavigationMixin
from .models_panel_duration import now as _now
from .models_panel_rendering import apply_jump_gutter, jump_hint_gutter_width
from .pane_entry_jump import KeyedPaneEntryJumpMixin
from .preview_panel_modal import PreviewPanelModal

_RAW_XPROMPT_FILENAME = "raw_xprompt.md"
_PROMPT_ICON = "📝"


class AliasHistoryModal(
    KeyedPaneEntryJumpMixin[str],
    OptionListNavigationMixin,
    ModalScreen[None],
):
    """View recorded prior runs for one alias or a collapsed bucket's members."""

    _option_list_id = "alias-history-list"

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("down", "next_option", "Next"),
        ("up", "prev_option", "Previous"),
        ("ctrl+n", "next_option", "Next"),
        ("ctrl+p", "prev_option", "Previous"),
        ("apostrophe", "jump_to_entry", "Jump"),
        ("enter", "open_prompt", "Prompt"),
        ("y", "copy_reference", "Copy"),
        ("ctrl+k", "load_more", "Load more"),
        ("r", "refresh", "Refresh"),
        (".", "toggle_hidden", "Hidden"),
    ]

    def __init__(self, entry: AliasHistoryEntryRequest) -> None:
        super().__init__()
        self._entry = entry
        self._include_hidden = False
        self._limit = get_model_alias_history_limit()
        self._view: AliasHistoryView | None = None
        self._error: str | None = None
        self._updating_highlight = False
        self._pending_keep: str | None = None
        self._load_worker: Worker[tuple[AliasHistoryView | None, str | None]] | None = (
            None
        )
        self._prompt_worker: Worker[tuple[str | None, str | None]] | None = None
        self._prompt_context: tuple[str | None, str] | None = None

    # -- composition ------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="alias-history-container"):
            yield Static(self._title_text(), id="alias-history-title")
            yield OptionList(*self._build_options(), id="alias-history-list")
            yield Static(self._detail_text(), id="alias-history-detail")
            yield Static(self._footer_markup(), id="alias-history-footer")

    def on_mount(self) -> None:
        option_list = self.query_one("#alias-history-list", OptionList)
        option_list.focus()
        self._start_load(initial_alias_history_load_request(self._entry))

    def on_unmount(self) -> None:
        for worker in (self._load_worker, self._prompt_worker):
            if worker is not None and not worker.is_finished:
                worker.cancel()

    # -- rendering ----------------------------------------------------------

    def _title_text(self) -> Text:
        return alias_history_title_text(self._entry, self._view)

    def _detail_text(self) -> Text:
        if self._view is None:
            return Text(self._error or "Loading history…", style="dim italic")
        return alias_history_detail_text(self._selected_run(), entry=self._entry)

    def _footer_markup(self) -> str:
        if self.jump_mode_active:
            action = "back" if self.jump_back_stack else "first"
            return f"JUMP ' {action}  <esc> cancel"
        has_more = self._view is not None and any(
            group.truncated for group in self._view.groups
        )
        return alias_history_footer_markup(
            include_hidden=self._include_hidden, has_more=has_more
        )

    def _build_options(self) -> list[Option]:
        if self._view is None:
            message = self._error or "Loading history…"
            style = "bold #D75F5F" if self._error else "dim italic"
            return [Option(Text(message, style=style), id="__loading__", disabled=True)]
        specs = build_alias_history_rows(self._view, entry=self._entry, now=_now())
        jump_mode = self.jump_mode_active
        jump_hints = self.jump_hints_by_key() if jump_mode else {}
        gutter_width = jump_hint_gutter_width(len(jump_hints)) if jump_mode else 0
        options: list[Option] = []
        for spec in specs:
            text = spec.text
            if jump_mode:
                text = apply_jump_gutter(
                    text, jump_hints.get(spec.option_id), gutter_width=gutter_width
                )
            options.append(Option(text, id=spec.option_id, disabled=spec.disabled))
        return options

    def _update_context(self) -> None:
        try:
            self.query_one("#alias-history-title", Static).update(self._title_text())
            self.query_one("#alias-history-footer", Static).update(
                self._footer_markup()
            )
            self.query_one("#alias-history-detail", Static).update(self._detail_text())
        except Exception:
            pass

    def _replace_display(self, *, keep: str | None = None) -> None:
        option_list = self.query_one("#alias-history-list", OptionList)
        option_list.clear_options()
        option_list.add_options(self._build_options())
        self._restore_highlight(option_list, keep)
        self._update_context()

    # -- highlight helpers --------------------------------------------------

    @staticmethod
    def _option_is_disabled(option_list: OptionList, index: int) -> bool:
        try:
            return option_list.get_option_at_index(index).disabled
        except Exception:
            return True

    @classmethod
    def _first_enabled_option_index(cls, option_list: OptionList) -> int | None:
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

    def _highlighted_option_id(self) -> str | None:
        option_list = self.query_one("#alias-history-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(highlighted)
        except Exception:
            return None
        return str(option.id) if option.id is not None else None

    def _selected_run(self) -> AliasHistoryRun | None:
        option_id = self._highlighted_option_id()
        if option_id is None or self._view is None:
            return None
        for group in self._view.groups:
            for run in group.runs:
                if alias_history_run_key(group.alias, run) == option_id:
                    return run
        return None

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if self._updating_highlight:
            return
        try:
            self.query_one("#alias-history-detail", Static).update(self._detail_text())
        except Exception:
            pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.action_open_prompt()

    # -- jump host hooks ------------------------------------------------

    def _jump_target_keys(self) -> list[str]:
        if self._view is None:
            return []
        return [
            alias_history_run_key(group.alias, run)
            for group in self._view.groups
            for run in group.runs
        ]

    def _jump_current_key(self) -> str | None:
        return self._highlighted_option_id()

    def _jump_select_key(self, key: str) -> None:
        self._replace_display(keep=key)

    def _jump_repaint(self) -> None:
        self._replace_display(keep=self._highlighted_option_id())

    def on_key(self, event: events.Key) -> None:
        if not self.jump_mode_active:
            return
        key = normalize_jump_key(event.key, event.character)
        if self.handle_jump_key(key):
            event.prevent_default()
            event.stop()

    # -- load lifecycle -------------------------------------------------

    def _start_load(self, request: AliasHistoryLoadRequest) -> None:
        if self._load_worker is not None and not self._load_worker.is_finished:
            self._load_worker.cancel()

        def task() -> tuple[AliasHistoryView | None, str | None]:
            try:
                return (
                    load_alias_history(
                        request.aliases,
                        limit_per_alias=request.limit_per_alias,
                        include_hidden=request.include_hidden,
                        freshness=request.freshness,
                    ),
                    None,
                )
            except Exception as exc:
                return None, str(exc)

        self._pending_keep = (
            self._highlighted_option_id() if self._view is not None else None
        )
        self._load_worker = self.run_worker(
            task, thread=True, exclusive=True, group="alias-history-load"
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._load_worker:
            self._on_load_worker(event)
        elif event.worker is self._prompt_worker:
            self._on_prompt_worker(event)

    def _on_load_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return
        keep = self._pending_keep
        self._load_worker = None
        self._pending_keep = None
        if event.state == WorkerState.CANCELLED:
            return
        if event.state == WorkerState.ERROR:
            self._error = (
                str(event.worker.error) if event.worker.error else "history load failed"
            )
            self.notify(
                f"Could not load alias history: {self._error}", severity="warning"
            )
            self._replace_display(keep=keep)
            return
        view, error = event.worker.result or (None, None)
        if error is not None or view is None:
            self._error = error or "history load failed"
            self.notify(
                f"Could not load alias history: {self._error}", severity="warning"
            )
            self._replace_display(keep=keep)
            return
        self._error = None
        self._view = view
        self._limit = view.limit_per_alias
        self._include_hidden = view.include_hidden
        self._replace_display(keep=keep)

    # -- re-query actions -------------------------------------------------

    def action_load_more(self) -> None:
        self._limit = doubled_alias_history_limit(self._limit)
        self._start_load(
            AliasHistoryLoadRequest(
                aliases=self._entry.aliases,
                limit_per_alias=self._limit,
                include_hidden=self._include_hidden,
                freshness="cached",
            )
        )

    def action_refresh(self) -> None:
        self._start_load(
            AliasHistoryLoadRequest(
                aliases=self._entry.aliases,
                limit_per_alias=self._limit,
                include_hidden=self._include_hidden,
                freshness="revalidate",
            )
        )

    def action_toggle_hidden(self) -> None:
        self._include_hidden = not self._include_hidden
        self._start_load(
            AliasHistoryLoadRequest(
                aliases=self._entry.aliases,
                limit_per_alias=self._limit,
                include_hidden=self._include_hidden,
                freshness="cached",
            )
        )

    # -- prompt preview ---------------------------------------------------

    def action_open_prompt(self) -> None:
        run = self._selected_run()
        if run is None:
            self.notify("No run selected.", severity="warning")
            return
        if self._prompt_worker is not None and not self._prompt_worker.is_finished:
            self._prompt_worker.cancel()
        artifact_dir = run.artifact_dir

        def task() -> tuple[str | None, str | None]:
            try:
                content = (Path(artifact_dir) / _RAW_XPROMPT_FILENAME).read_text(
                    encoding="utf-8", errors="replace"
                )
                return content, None
            except OSError as exc:
                return None, str(exc)

        self._prompt_context = (self._highlighted_option_id(), artifact_dir)
        self._prompt_worker = self.run_worker(
            task, thread=True, exclusive=True, group="alias-history-prompt"
        )

    def _on_prompt_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return
        context = self._prompt_context
        self._prompt_worker = None
        self._prompt_context = None
        if event.state != WorkerState.SUCCESS or context is None:
            if event.state == WorkerState.ERROR:
                self.notify(
                    "Could not read the prompt for this run.", severity="warning"
                )
            return
        selected_key, artifact_dir = context
        content, error = event.worker.result or (None, None)
        if error is not None or content is None:
            self.notify("Could not read the prompt for this run.", severity="warning")
            return
        if self._highlighted_option_id() != selected_key:
            return
        self.app.push_screen(  # type: ignore[attr-defined]
            PreviewPanelModal(
                PreviewPayload(
                    content=content,
                    lexer="markdown",
                    title=self._entry.title_label,
                    kind_label="alias history prompt",
                    icon=_PROMPT_ICON,
                    source_path=str(Path(artifact_dir) / _RAW_XPROMPT_FILENAME),
                    default_view="rendered",
                )
            )
        )

    # -- copy ---------------------------------------------------------------

    def action_copy_reference(self) -> None:
        run = self._selected_run()
        if run is None:
            self.notify("No run selected.", severity="warning")
            return
        reference = reference_for_agent_name(run.agent_name) if run.agent_name else None
        if reference is None:
            self.notify(
                "This run has no durable agent name to copy.", severity="warning"
            )
            return
        schedule_copy_delivery(
            self,
            f"@{reference}",
            copied_label=f"agent reference ({reference})",
            task_name="sase-copy-alias-history-agent-reference",
        )

    # -- close ------------------------------------------------------------

    def action_close(self) -> None:
        self.dismiss(None)


__all__ = ["AliasHistoryModal"]
