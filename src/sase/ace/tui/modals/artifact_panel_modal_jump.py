"""Jump-mode behavior for the artifact panel modal."""

from __future__ import annotations

from typing import Any

from textual import events
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.actions.navigation.jump_hints import (
    build_jump_hint_maps,
    normalize_jump_key,
)

from .artifact_panel_modal_formatting import (
    _ARTIFACT_PANEL_NORMAL_HINTS,
    row_label,
    state_message,
)
from .artifact_panel_state import (
    ARTIFACT_PANEL_GLOBAL_SEARCH_LIMIT,
    build_artifact_search_rows,
)


class ArtifactPanelJumpMixin:
    def _jump_candidate_row_ids(self: Any) -> list[str]:
        option_list = self.query_one("#artifact-panel-list", OptionList)
        row_ids: list[str] = []
        for index in range(option_list.option_count):
            option = option_list.get_option_at_index(index)
            option_id = option.id
            if option.disabled or option_id is None:
                continue
            if option_id in self._row_by_option_id:
                row_ids.append(option_id)
        return row_ids

    def _sync_jump_hints_to_visible_rows(self: Any) -> None:
        visible = set(self._jump_candidate_row_ids())
        self._entry_jump_hint_to_row_id = {
            hint: row_id
            for hint, row_id in self._entry_jump_hint_to_row_id.items()
            if row_id in visible
        }
        self._entry_jump_row_id_to_hint = {
            row_id: hint
            for row_id, hint in self._entry_jump_row_id_to_hint.items()
            if row_id in visible
        }
        if not self._entry_jump_hint_to_row_id:
            self._clear_entry_jump_hints()

    def _clear_entry_jump_hints(self: Any) -> None:
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_row_id = {}
        self._entry_jump_row_id_to_hint = {}
        self._update_jump_footer()

    def _exit_entry_jump_mode(self: Any) -> None:
        prefer_row_id = self._highlighted_row_id()
        self._clear_entry_jump_hints()
        if self._search_text:
            self._render_search_options()
        elif self._detail is not None:
            self._replace_options(
                self._build_options(self._detail),
                prefer_row_id=prefer_row_id,
            )

    def _jump_to_row_id(self: Any, row_id: str) -> bool:
        if row_id not in self._row_by_option_id:
            self._exit_entry_jump_mode()
            return True

        self._clear_entry_jump_hints()
        self._replace_options(
            self._build_current_options_without_hints(),
            prefer_row_id=row_id,
        )
        self._state.selected_row_id = row_id
        return True

    def _build_current_options_without_hints(self: Any) -> list[Option]:
        if self._search_text:
            query = self._search_text
            results = self._search_results
            if not query:
                return [
                    Option(
                        state_message(
                            "Global artifact search",
                            "Type a query to search the artifact index.",
                            style="cyan",
                        ),
                        id="__search_prompt__",
                        disabled=True,
                    )
                ]
            if self._search_error is not None:
                return [
                    Option(
                        state_message(
                            f"Search failed: {self._search_error}",
                            "Edit the query to try again.",
                            style="red",
                        ),
                        id="__search_error__",
                        disabled=True,
                    )
                ]
            if results is None:
                return [
                    Option(
                        state_message(
                            f"Searching for {query!r}",
                            "Checking the artifact index.",
                            style="cyan",
                        ),
                        id="__search_loading__",
                        disabled=True,
                    )
                ]
            if not results:
                return [
                    Option(
                        state_message(
                            f"No global results for {query!r}",
                            "Try another query or return to local navigation.",
                            style="yellow",
                        ),
                        id="__search_empty__",
                        disabled=True,
                    )
                ]
            self._row_by_option_id = {}
            options: list[Option] = []
            panel_rows = build_artifact_search_rows(
                results,
                query=query,
                limit=ARTIFACT_PANEL_GLOBAL_SEARCH_LIMIT,
            )
            for row in panel_rows.rows:
                options.append(
                    Option(row_label(row), id=row.id, disabled=not row.selectable)
                )
                if row.selectable:
                    self._row_by_option_id[row.id] = row
            return options

        if self._detail is None:
            return []
        return self._build_options(self._detail)

    def _handle_entry_jump_key(self: Any, key: str) -> bool:
        if not self._entry_jump_mode_active:
            return False
        if key == "escape":
            self._exit_entry_jump_mode()
            return True

        if key == "apostrophe":
            last_row_id = self._entry_jump_last_row_id
            if last_row_id is not None and last_row_id in self._row_by_option_id:
                current = self._highlighted_row_id()
                if current is not None:
                    self._entry_jump_last_row_id = current
                return self._jump_to_row_id(last_row_id)
            key = "1"

        row_id = self._entry_jump_hint_to_row_id.get(key)
        if row_id is None:
            self._exit_entry_jump_mode()
            return True

        current = self._highlighted_row_id()
        if current is not None:
            self._entry_jump_last_row_id = current
        return self._jump_to_row_id(row_id)

    def _update_jump_footer(self: Any) -> None:
        try:
            footer = self.query_one("#artifact-panel-hints", Static)
        except Exception:
            return

        if self._entry_jump_mode_active:
            action = "back" if self._entry_jump_last_row_id is not None else "first"
            footer.update(f"JUMP ' {action}  <esc> cancel  enter opens selected")
        else:
            footer.update(_ARTIFACT_PANEL_NORMAL_HINTS)

    def action_jump_to_entry(self: Any) -> None:
        row_ids = self._jump_candidate_row_ids()
        if not row_ids:
            return
        self._entry_jump_hint_to_row_id, self._entry_jump_row_id_to_hint = (
            build_jump_hint_maps(row_ids)
        )
        if not self._entry_jump_hint_to_row_id:
            return

        self._entry_jump_mode_active = True
        self._update_jump_footer()
        prefer_row_id = self._highlighted_row_id()
        if self._search_text:
            self._render_search_options()
        elif self._detail is not None:
            self._replace_options(
                self._build_options(self._detail),
                prefer_row_id=prefer_row_id,
            )

    def on_key(self: Any, event: events.Key) -> None:
        if not self._entry_jump_mode_active:
            return

        key = normalize_jump_key(event.key, event.character)
        if self._handle_entry_jump_key(key):
            event.prevent_default()
            event.stop()
