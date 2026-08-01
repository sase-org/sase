"""Sticky misspelling highlight overlay for ``PromptTextArea``."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from rich.style import Style
from textual.widgets._text_area import TextAreaTheme

from sase.ace.tui.widgets._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from sase.core.word_lookup import MISSPELLING_COLOR, natural_word_ranges
from sase.xprompt._literal_zones import code_literal_ranges

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class MisspellingHighlightMixin(_MixinBase):
    """Underline words the user's ``K`` presses have proven misspelled.

    Structural overlays (xprompt, artifact, alt, placeholder, code block) are
    registered after this mixin in ``PromptTextArea``'s base list and therefore
    win on overlap; this overlay only ever adds an underline beneath base
    Markdown styling.
    """

    if TYPE_CHECKING:

        def _append_highlight_span(
            self,
            start: int,
            end: int,
            style_name: str,
        ) -> None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._misspelling_cache_text: str | None = None
        self._misspelling_cache_generation: int | None = None
        self._misspelling_cached_spans: tuple[tuple[int, int], ...] | None = None
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        """Register the misspelling style and schedule the first warm cache."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._register_misspelling_text_area_theme()
        warm = getattr(self.app, "warm_misspellings", None)
        if callable(warm):
            warm()

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        self._register_misspelling_text_area_theme()

    def _register_jinja_text_area_theme(self) -> None:
        register_jinja = getattr(super(), "_register_jinja_text_area_theme", None)
        if callable(register_jinja):
            register_jinja()
        self._register_misspelling_text_area_theme(_JINJA_THEME_NAME, apply=False)

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        for start, end in self._misspelling_spans_for_document():
            self._append_highlight_span(start, end, "spell.misspelled")

    def _refresh_misspelling_overlay(self) -> None:
        self._build_highlight_map()
        self.refresh()

    def _misspelling_spans_for_document(self) -> tuple[tuple[int, int], ...]:
        if not self._misspelling_highlight_enabled():
            return ()
        misspelled = self._misspelled_words_from_app()
        if not misspelled:
            return ()

        text = self.text
        generation = self._misspellings_generation_from_app()
        if (
            self._misspelling_cache_text != text
            or self._misspelling_cache_generation != generation
        ):
            self._misspelling_cache_text = text
            self._misspelling_cache_generation = generation
            self._misspelling_cached_spans = _scan_misspelling_spans(text, misspelled)
        return self._misspelling_cached_spans or ()

    def _active_app(self) -> Any | None:
        """Return the running app, or ``None`` before this widget is mounted.

        ``TextArea.__init__`` calls ``_build_highlight_map()`` synchronously
        while constructing a standalone (unmounted) ``PromptTextArea``, at
        which point the ``app`` property raises rather than returning ``None``.
        """
        try:
            return self.app
        except Exception:
            return None

    def _misspelling_highlight_enabled(self) -> bool:
        app = self._active_app()
        if app is None:
            return True
        getter = getattr(app, "get_prompt_spellcheck_settings", None)
        if not callable(getter):
            return True
        try:
            settings = getter()
        except Exception:
            return True
        return bool(getattr(settings, "highlight", True))

    def _misspelled_words_from_app(self) -> frozenset[str]:
        app = self._active_app()
        if app is None:
            return frozenset()
        provider = getattr(app, "misspelled_words", None)
        if not callable(provider):
            return frozenset()
        try:
            words = provider()
        except Exception:
            return frozenset()
        return words if isinstance(words, frozenset) else frozenset()

    def _misspellings_generation_from_app(self) -> int:
        app = self._active_app()
        if app is None:
            return 0
        provider = getattr(app, "misspellings_generation", None)
        if not callable(provider):
            return 0
        try:
            generation = provider()
        except Exception:
            return 0
        return generation if isinstance(generation, int) else 0

    def _register_misspelling_text_area_theme(
        self,
        theme_name: str | None = None,
        *,
        apply: bool = True,
    ) -> None:
        active_name = theme_name or str(getattr(self, "theme", "css") or "css")
        base = self._resolve_misspelling_base_theme(active_name)
        syntax_styles = dict(base.syntax_styles)
        syntax_styles["spell.misspelled"] = Style(
            color=MISSPELLING_COLOR,
            underline=True,
        )
        theme = dataclasses.replace(
            base,
            name=active_name,
            syntax_styles=syntax_styles,
        )
        self.register_theme(theme)
        if apply:
            self._set_theme(theme.name)

    def _resolve_misspelling_base_theme(self, theme_name: str) -> TextAreaTheme:
        try:
            theme: TextAreaTheme | None = self._themes[theme_name]
        except KeyError:
            theme = TextAreaTheme.get_builtin_theme(theme_name)
        if theme is None:
            fallback = TextAreaTheme.get_builtin_theme("css")
            assert fallback is not None
            return fallback
        return theme


def _scan_misspelling_spans(
    text: str,
    misspelled: frozenset[str],
) -> tuple[tuple[int, int], ...]:
    """Return spans for every word in *text* casefolding into *misspelled*.

    Words inside fenced or inline code literals are skipped; structural
    overlays already win on overlap through MRO placement, so this scan need
    not special-case Jinja/xprompt/placeholder token interiors.
    """
    if len(text.encode("utf-8")) > _MAX_OVERLAY_BYTES:
        return ()
    if text.count("\n") > _MAX_OVERLAY_LINES:
        return ()

    literal_ranges = code_literal_ranges(text) if "`" in text or "~~~" in text else []
    spans: list[tuple[int, int]] = []
    literal_index = 0
    for start, end, word in natural_word_ranges(text):
        if word.casefold() not in misspelled:
            continue
        while (
            literal_index < len(literal_ranges)
            and literal_ranges[literal_index][1] <= start
        ):
            literal_index += 1
        if (
            literal_index < len(literal_ranges)
            and literal_ranges[literal_index][0]
            <= start
            < literal_ranges[literal_index][1]
        ):
            continue
        spans.append((start, end))
    return tuple(spans)


__all__ = ["MisspellingHighlightMixin"]
