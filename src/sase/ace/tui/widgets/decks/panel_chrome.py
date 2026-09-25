"""Deck panel chrome helpers extracted from ``panel.py``."""

from __future__ import annotations

from typing import Any

from .model import DeckId, RenderMode
from .titles import CardTab, deck_subtitle, deck_title

_BORDER_LABEL_RESERVED_CELLS = 4

_FALLBACK_ACCENTS = {
    DeckId.MAIN: "#B48EAD",
    DeckId.FILES: "green",
    DeckId.TOOLS: "#87D7FF",
}


class DeckPanelChromeMixin:
    """Border title and subtitle helpers for ``DeckPanel``."""

    _panel_index: int
    _deck: DeckId
    _focused: bool

    def _resolve_accent(self, deck: DeckId) -> str:
        if deck is DeckId.MAIN:
            # ``app.theme_variables`` is only rebuilt lazily by Textual's CSS
            # pass, so it can still hold a previous theme's colors here.
            try:
                secondary = self.app.current_theme.secondary  # type: ignore[attr-defined]
                if secondary:
                    return str(secondary)
            except Exception:
                pass
            return _FALLBACK_ACCENTS[DeckId.MAIN]
        return _FALLBACK_ACCENTS[deck]

    def _subscribe_theme_changes(self) -> None:
        """Recolor the chrome live when the app theme changes."""
        try:
            self.app.theme_changed_signal.subscribe(  # type: ignore[attr-defined]
                self, self._on_app_theme_changed
            )
        except Exception:
            pass

    def _on_app_theme_changed(self, _theme: object) -> None:
        self.refresh_chrome()
        try:
            document = self._main_document  # type: ignore[attr-defined]
            if document.cards and self._is_spread_active_for(DeckId.MAIN):
                # The spread render key includes the accent, so this repaints
                # the card separators without disturbing the scroll anchor.
                self.main_view.show_document(  # type: ignore[attr-defined]
                    document, preferred_card=None, mode=RenderMode.SPREAD
                )
        except Exception:
            pass

    def _accent_for(self) -> dict[DeckId, str]:
        return {deck: self._resolve_accent(deck) for deck in DeckId}

    def _chrome_width(self) -> int:
        """Return the cells a border title or subtitle can actually use.

        ``size.width`` is the content width. Textual draws a border label into
        that many cells, reserves 2 per corner and truncates with ``…``, so the
        real budget is ``size.width - 4``.
        """
        try:
            width = int(self.size.width)  # type: ignore[attr-defined]
        except Exception:
            width = 0
        return max(1, width - _BORDER_LABEL_RESERVED_CELLS) if width > 0 else 80

    def _deck_switch_hint(self) -> str | None:
        """Return the live deck-switch hint for the empty-state card."""
        try:
            from ...keymaps import key_display_name
        except Exception:
            return None
        try:
            registry = getattr(getattr(self, "app", None), "_keymap_registry", None)
            if registry is not None:
                app_keys = getattr(registry, "app", None)
                next_key = key_display_name(str(getattr(app_keys, "next_deck", "")))
                prev_key = key_display_name(str(getattr(app_keys, "prev_deck", "")))
                pick_key = key_display_name(str(getattr(app_keys, "pick_deck", "")))
            else:
                next_key = prev_key = pick_key = ""
        except Exception:
            return None
        if not next_key or not prev_key:
            return None
        if pick_key:
            return f"{pick_key} pick deck · {next_key}/{prev_key} cycle decks"
        return f"{next_key} next deck · {prev_key} previous deck"

    def _main_tabs(self) -> tuple[CardTab, ...]:
        tabs: list[CardTab] = []
        for card in self._main_document.cards:  # type: ignore[attr-defined]
            tabs.append(CardTab(card.card_id, card.title))
        return tuple(tabs)

    def _files_tabs(self) -> tuple[CardTab, ...]:
        try:
            view = self.file_view  # type: ignore[attr-defined]
            file_list = list(getattr(view, "_file_list", []))
            index = int(getattr(view, "_current_file_index", 0))
        except Exception:
            return ()
        tabs: list[CardTab] = []
        for i, _page in enumerate(file_list):
            label = f"file {i + 1}"
            if i == index:
                try:
                    current = view.current_source_label()
                except Exception:
                    current = None
                if current:
                    label = current
            tabs.append(CardTab(f"file-{i}", label))
        return tuple(tabs)

    def _active_tab_index(self) -> int | None:
        if self._deck is DeckId.MAIN:
            ids = [card.card_id for card in self._main_document.cards]  # type: ignore[attr-defined]
            active = getattr(self, "_main_active_card", None)
            if active is None:
                return None if not ids else None
            try:
                return ids.index(active)
            except ValueError:
                return None
        if self._deck is DeckId.FILES:
            try:
                view = self.file_view  # type: ignore[attr-defined]
                if not getattr(view, "_file_list", []):
                    return None
                return int(getattr(view, "_current_file_index", 0))
            except Exception:
                return None
        return 0

    def _is_spread_active_for(self, deck: DeckId) -> bool:
        try:
            modes = getattr(self, "_render_mode", None)
            if isinstance(modes, dict):
                return modes.get(deck) is RenderMode.SPREAD
        except Exception:
            pass
        return False

    def _is_spread_active(self) -> bool:
        return self._is_spread_active_for(self._deck)

    def refresh_chrome(self) -> None:
        """Recompute the border title and subtitle."""
        width = self._chrome_width()
        accent_for = self._accent_for()
        accent = accent_for[self._deck]
        if self._deck is DeckId.MAIN:
            tabs = self._main_tabs()
        elif self._deck is DeckId.FILES:
            tabs = self._files_tabs()
        else:
            tabs = (CardTab("llm-calls", "LLM Calls"),)
        active_index = self._active_tab_index()
        if self._deck is DeckId.MAIN and not tabs:
            active_index = None
        try:
            self.border_title = deck_title(  # type: ignore[attr-defined]
                self._deck,
                tabs,
                active_index,
                width=width,
                accent=accent,
                focused=self._focused,
            )
        except Exception:
            pass
        if self._deck is DeckId.FILES:
            from .titles import file_line_status

            try:
                status = file_line_status(
                    self._file_visible_lines,  # type: ignore[attr-defined]
                    self._file_total_lines,  # type: ignore[attr-defined]
                    self._file_capped,  # type: ignore[attr-defined]
                    editor_key="E",
                )
            except Exception:
                status = None
        else:
            status = None
        try:
            self.border_subtitle = deck_subtitle(  # type: ignore[attr-defined]
                self._deck,
                self._availability,  # type: ignore[attr-defined]
                status=status,
                width=width,
                accent_for=accent_for,
                spread=self._is_spread_active(),
            )
        except Exception:
            pass


__all__ = ["DeckPanelChromeMixin"]
