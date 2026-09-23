"""Guarded bead option list with viewport-following highlights."""

from __future__ import annotations

from typing import Any

from textual.widgets import OptionList
from textual.widgets.option_list import Option

from .entry_navigation import (
    prewarm_option_render_cache,
    reveal_option_list_highlight,
)


class BeadsOptionList(OptionList):
    """Bead rows whose guarded highlights retain viewport following."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._programmatic_update = False

    def set_highlight(self, index: int | None) -> None:
        self._programmatic_update = True
        try:
            self._assign_highlight(index)
        finally:
            self._programmatic_update = False

    def replace_options(
        self,
        options: list[Option],
        *,
        highlighted: int | None,
    ) -> None:
        self._programmatic_update = True
        try:
            self.clear_options()
            self.add_options(options)
            self._assign_highlight(highlighted)
            prewarm_option_render_cache(self)
        finally:
            self._programmatic_update = False

    def _assign_highlight(self, index: int | None) -> None:
        self.highlighted = index
        reveal_option_list_highlight(self)

    def watch_highlighted(self, highlighted: int | None) -> None:
        if self._programmatic_update:
            return
        super().watch_highlighted(highlighted)


__all__ = ["BeadsOptionList"]
