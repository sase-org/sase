"""Off-thread syntax preparation, caching, and theme invalidation.

Lexing never runs on Textual's message pump: a section is only prepared by a
pump-free worker spawned after the first paint, sequenced current-section
first, then the rest of the document. Completed outcomes -- including plain
and failed ones -- are cached across documents so revisiting a section never
re-lexes it, and a theme change restyles cached tokens without re-lexing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.ace.tui.widgets.vim_search_controller import VimSearchController
from sase.pager._labels import PagerLabelLayer
from sase.pager._layout import ComposedBody, compose_body
from sase.pager._syntax_cache import (
    ResultCacheKey,
    StyledCacheKey,
    StyledTextCache,
    SyntaxResultCache,
    content_digest,
)
from sase.pager.document import PagerDocument, PagerSection, section_syntax_language
from sase.pager.syntax import (
    SyntaxDisposition,
    SyntaxResult,
    SyntaxRole,
    highlight_source,
    normalize_language,
    style_source_text,
    syntax_hint_alias,
    text_has_producer_style,
)
from sase.pager.syntax_theme import SyntaxPalette, syntax_palette_from_theme

#: Once a document's already-highlighted spans cross this, remaining
#: sections in that document are left plain rather than queued for lexing
#: (design doc: "bound a document to 200,000 prepared spans"). Distinct from
#: ``_syntax_cache.MAX_CACHED_SPANS``, which bounds the cross-document cache.
MAX_DOCUMENT_SYNTAX_SPANS: Final = 200_000


@dataclass(frozen=True, slots=True)
class _PreparedSection:
    """A ready-to-paint styled section and its subject-line language hint."""

    styled_text: Text
    hint: str | None


def _lex_and_style(
    source: str,
    language: str,
    base_text: Text,
    rich_styles: Mapping[SyntaxRole, Style],
) -> tuple[SyntaxResult, Text]:
    """Lex and style in one thread hop for the common cold-cache case."""
    result = highlight_source(source, language, base_text=base_text)
    styled = style_source_text(base_text, result, rich_styles)
    return result, styled


class PagerSyntaxMixin:
    """Own background syntax preparation, its caches, and theme invalidation."""

    document: PagerDocument
    _body: ComposedBody | None
    _body_width: int | None
    _label_layer: PagerLabelLayer | None
    _label_pending_prefix: str
    _search: VimSearchController
    _syntax_palette: SyntaxPalette
    _syntax_generation: int
    _syntax_prepared: dict[str, _PreparedSection]
    _syntax_attempted: set[str]
    _syntax_result_cache: SyntaxResultCache
    _syntax_styled_cache: StyledTextCache
    _syntax_restart_requested: bool
    _syntax_pass_running: bool
    _syntax_document_span_budget_used: int

    def _init_syntax_state(self: Any) -> None:
        self._syntax_palette = syntax_palette_from_theme(None)
        self._syntax_generation = 0
        self._syntax_prepared = {}
        self._syntax_attempted = set()
        self._syntax_result_cache = SyntaxResultCache()
        self._syntax_styled_cache = StyledTextCache()
        self._syntax_restart_requested = False
        self._syntax_pass_running = False
        self._syntax_document_span_budget_used = 0

    def _reset_syntax_for_new_document(self: Any) -> None:
        """Drop per-document state; the cross-document caches stay intact."""
        self._syntax_generation += 1
        self._syntax_prepared = {}
        self._syntax_attempted = set()
        self._syntax_restart_requested = False
        self._syntax_document_span_budget_used = 0

    def _start_syntax_preparation_after_paint(self: Any) -> None:
        self.call_after_refresh(self._schedule_syntax_preparation)

    def _on_app_theme_changed(self: Any) -> None:
        palette = syntax_palette_from_theme(self._current_syntax_theme())
        if palette.signature == self._syntax_palette.signature:
            return
        self._syntax_palette = palette
        self._syntax_styled_cache.clear()
        self._syntax_prepared = {}
        self._syntax_attempted = set()
        self._syntax_document_span_budget_used = 0
        self.call_after_refresh(self._schedule_syntax_preparation)

    def _current_syntax_theme(self: Any) -> Any | None:
        app = getattr(self, "app", None)
        return getattr(app, "current_theme", None)

    def _current_syntax_hint(self: Any) -> str | None:
        if not self.document.sections:
            return None
        section = self._current_section()
        entry = self._syntax_prepared.get(section.identity)
        return None if entry is None else entry.hint

    def _prepared_section_texts(self: Any) -> dict[int, Text]:
        prepared = self._syntax_prepared
        if not prepared:
            return {}
        texts: dict[int, Text] = {}
        for index, section in enumerate(self.document.sections):
            entry = prepared.get(section.identity)
            if entry is not None:
                texts[index] = entry.styled_text
        return texts

    def _document_has_pending_syntax_work(self: Any) -> bool:
        if not getattr(self, "syntax_enabled", True):
            return False
        attempted = self._syntax_attempted
        for section in self.document.sections:
            if section.identity in attempted:
                continue
            if section_syntax_language(section) is not None:
                return True
        return False

    def _schedule_syntax_preparation(self: Any) -> None:
        if self._syntax_pass_running:
            self._syntax_restart_requested = True
            return
        if not self._document_has_pending_syntax_work():
            return
        self._syntax_pass_running = True
        self._spawn_syntax_preparation_task(self.document, self._syntax_generation)

    def _spawn_syntax_preparation_task(
        self: Any,
        document: PagerDocument,
        generation: int,
    ) -> None:
        spawn_pump_free_task(
            self,
            self._run_syntax_preparation(document, generation),
            name="sase-pager-syntax",
            registry_attr="_pump_free_syntax_tasks",
        )

    def _syntax_prepare_order(self: Any) -> list[int]:
        total = len(self.document.sections)
        if total == 0:
            return []
        current = self._current_section_index()
        return [current, *(index for index in range(total) if index != current)]

    def _syntax_is_stale(
        self: Any,
        document: PagerDocument,
        generation: int,
    ) -> bool:
        return generation != self._syntax_generation or self.document is not document

    async def _run_syntax_preparation(
        self: Any,
        document: PagerDocument,
        generation: int,
    ) -> None:
        try:
            self._syntax_palette = syntax_palette_from_theme(
                self._current_syntax_theme()
            )
            order = self._syntax_prepare_order()
            position = 0
            published_first = False
            while position < len(order):
                if self._syntax_is_stale(document, generation):
                    return
                if self._syntax_restart_requested:
                    self._syntax_restart_requested = False
                    order = self._syntax_prepare_order()
                    position = 0
                    continue
                section_index = order[position]
                position += 1
                section = document.sections[section_index]
                if section.identity in self._syntax_attempted:
                    continue
                changed = await self._prepare_one_section(document, generation, section)
                if self._syntax_is_stale(document, generation):
                    return
                if not changed:
                    continue
                if not published_first:
                    published_first = True
                    self._publish_syntax_update()
            if published_first:
                self._publish_syntax_update()
        finally:
            self._syntax_pass_running = False
            if self._syntax_restart_requested:
                self._syntax_restart_requested = False
                self._schedule_syntax_preparation()

    async def _prepare_one_section(
        self: Any,
        document: PagerDocument,
        generation: int,
        section: PagerSection,
    ) -> bool:
        """Prepare one section; return whether it now paints differently."""
        language = section_syntax_language(section)
        canonical_language = None if language is None else normalize_language(language)
        if language is None or canonical_language is None:
            self._syntax_attempted.add(section.identity)
            return False
        if self._syntax_document_span_budget_used >= MAX_DOCUMENT_SYNTAX_SPANS:
            self._syntax_attempted.add(section.identity)
            return False

        source = section.plain_text
        base_text = section.body_text
        digest = await asyncio.to_thread(content_digest, source)
        if self._syntax_is_stale(document, generation):
            return False

        result_key = ResultCacheKey(digest=digest, language=canonical_language)
        result = self._syntax_result_cache.get(result_key)
        producer_eligible = text_has_producer_style(base_text)
        styled_key = StyledCacheKey(
            digest=digest,
            language=canonical_language,
            theme_signature=self._syntax_palette.signature,
            producer_eligible=producer_eligible,
        )

        if result is None:
            result, styled = await asyncio.to_thread(
                _lex_and_style,
                source,
                language,
                base_text,
                self._syntax_palette.rich_styles,
            )
            if self._syntax_is_stale(document, generation):
                return False
            self._syntax_result_cache.put(result_key, result)
            self._syntax_styled_cache.put(styled_key, styled)
        else:
            styled = self._syntax_styled_cache.get(styled_key)
            if styled is None:
                styled = await asyncio.to_thread(
                    style_source_text,
                    base_text,
                    result,
                    self._syntax_palette.rich_styles,
                )
                if self._syntax_is_stale(document, generation):
                    return False
                self._syntax_styled_cache.put(styled_key, styled)

        self._syntax_attempted.add(section.identity)
        self._syntax_document_span_budget_used += len(result.spans)
        if result.disposition is not SyntaxDisposition.HIGHLIGHTED:
            return False
        hint = syntax_hint_alias(result.language) if result.language else None
        self._syntax_prepared[section.identity] = _PreparedSection(
            styled_text=styled, hint=hint
        )
        return True

    def _publish_syntax_update(self: Any) -> None:
        width = self._body_width
        if width is None:
            return
        self._label_layer = self._build_label_layer(width)
        mark = getattr(self, "_goto_mark", None)
        accent_fn = getattr(self, "_goto_accent_for_mark", None)
        self._body = compose_body(
            self.document,
            width,
            label_layer=self._label_layer,
            pending_prefix=self._label_pending_prefix,
            prepared_sections=self._prepared_section_texts(),
            goto_mark=mark,
            goto_accent=accent_fn()
            if mark is not None and accent_fn is not None
            else None,
        )
        if self._search.is_active:
            self._search.refresh_styled_base()
        else:
            self.query_one("#pager-body", Static).update(self._body.renderable)
        self._update_subject()


__all__ = ["MAX_DOCUMENT_SYNTAX_SPANS", "PagerSyntaxMixin"]
