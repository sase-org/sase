"""Destination list behavior for the unified xprompt save modal."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from .unified_xprompt_save_support import (
    SaveMode,
    UnifiedDestinationList,
    UnifiedSaveLocation,
)

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


class UnifiedXPromptSaveDestinationsMixin(_MixinBase):
    """Build, select, and navigate destination rows."""

    if TYPE_CHECKING:
        _last_used: dict[SaveMode, str]
        _mode: SaveMode
        _preferred_snippet_path: str | None
        _preview_tab: str
        _updating_options: bool

        @property
        def _locations(self) -> list[UnifiedSaveLocation]: ...

        def _collides(self, row: UnifiedSaveLocation, name: str) -> bool: ...
        def _current_collision(self) -> bool: ...
        def _current_name(self) -> str: ...
        def _disarm(self) -> None: ...

    def _default_location_path(self) -> str | None:
        if self._mode == "snippet" and self._preferred_snippet_path:
            preferred_snippet = self._preferred_snippet_path
            if any(
                row.location.path == preferred_snippet and row.is_selectable
                for row in self._locations
            ):
                return preferred_snippet
        preferred = self._last_used.get(self._mode)
        if preferred and any(
            row.location.path == preferred and row.is_selectable
            for row in self._locations
        ):
            return preferred
        if self._mode == "xprompt":
            for predicate in (
                lambda row: row.group == "Project",
                lambda row: row.location.label.startswith("Home "),
            ):
                match = next(
                    (
                        row
                        for row in self._locations
                        if row.is_selectable and predicate(row)
                    ),
                    None,
                )
                if match is not None:
                    return match.location.path
        match = next((row for row in self._locations if row.is_selectable), None)
        return match.location.path if match is not None else None

    def _rebuild_options(self, preferred_path: str | None) -> None:
        option_list = self.query_one("#unified-save-locations", UnifiedDestinationList)
        self._updating_options = True
        try:
            option_list.clear_options()
            for group in dict.fromkeys(row.group for row in self._locations):
                option_list.add_option(
                    Option(
                        Text(f"── {group} ──", style="bold dim"),
                        id=f"header-{group}",
                        disabled=True,
                    )
                )
                for index, row in enumerate(self._locations):
                    if row.group != group:
                        continue
                    option_list.add_option(
                        Option(
                            self._row_label(row),
                            id=f"location-{index}",
                            disabled=not row.is_selectable,
                        )
                    )
            highlighted: int | None = None
            for index in range(option_list.option_count):
                option = option_list.get_option_at_index(index)
                if not option.id or getattr(option, "disabled", False):
                    continue
                highlighted_row = self._row_for_option_id(str(option.id))
                if highlighted is None:
                    highlighted = index
                if (
                    highlighted_row is not None
                    and highlighted_row.location.path == preferred_path
                ):
                    highlighted = index
                    break
            option_list.highlighted = highlighted
        finally:
            self._updating_options = False
        self._preview_tab = "diff" if self._current_collision() else "draft"

    def _row_label(self, row: UnifiedSaveLocation) -> Text:
        text = Text()
        # These fallback glyphs render in the pinned visual-test font; color
        # emoji folder/file glyphs otherwise become tofu squares.
        icon = "▣" if row.location.location_type == "directory" else "◆"
        text.append(f"  {icon} ")
        text.append(row.location.label, style="bold" if row.is_selectable else "dim")
        text.append(f"  {len(row.names)}", style="dim")
        if self._collides(row, self._current_name()):
            text.append(" ●", style="bold")
        if row.will_create:
            text.append("  (will be created)", style="italic dim")
        if row.builtin:
            text.append("  dev", style="italic dim")
        text.append(f"\n     {row.display_path}", style="dim")
        if row.disabled_reason:
            text.append(f"  ({row.disabled_reason})", style="italic dim")
        return text

    def _row_for_option_id(self, option_id: str) -> UnifiedSaveLocation | None:
        if not option_id.startswith("location-"):
            return None
        try:
            index = int(option_id.removeprefix("location-"))
        except ValueError:
            return None
        return self._locations[index] if 0 <= index < len(self._locations) else None

    def _selected_row(self) -> UnifiedSaveLocation | None:
        option_list = self.query_one("#unified-save-locations", UnifiedDestinationList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        option = option_list.get_option_at_index(highlighted)
        if not option.id or getattr(option, "disabled", False):
            return None
        return self._row_for_option_id(str(option.id))

    def _selected_location_path(self) -> str | None:
        row = self._selected_row()
        return row.location.path if row is not None else None

    def action_next_location(self) -> None:
        self._move_location(1)

    def action_prev_location(self) -> None:
        self._move_location(-1)

    def _move_location(self, direction: int) -> None:
        option_list = self.query_one("#unified-save-locations", OptionList)
        current = option_list.highlighted
        start = (
            current
            if current is not None
            else (-1 if direction > 0 else option_list.option_count)
        )
        for index in range(
            start + direction,
            option_list.option_count if direction > 0 else -1,
            direction,
        ):
            option = option_list.get_option_at_index(index)
            if option.id and not getattr(option, "disabled", False):
                self._disarm()
                option_list.highlighted = index
                return


__all__ = ["UnifiedXPromptSaveDestinationsMixin"]
