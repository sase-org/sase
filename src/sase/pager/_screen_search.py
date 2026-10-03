"""``VimSearchController`` host protocol for ``PagerScreen``."""

from __future__ import annotations

from bisect import bisect_left
from typing import Any

from rich.text import Text
from textual.cache import LRUCache
from textual.widgets import Static

from sase.ace.tui.widgets._vim_search import SearchSpan
from sase.ace.tui.widgets.vim_search_controller import (
    CURRENT_MATCH_STYLE,
    MATCH_STYLE,
    SearchViewport,
    VimSearchMode,
)
from sase.pager._body_lines import (
    build_span_index,
    logical_line_end,
    logical_line_starts,
    slice_styled_line,
)
from sase.pager._labels import style_target_accents
from sase.pager._layout import search_corpus, styled_search_base

#: Bound for the per-search base-line LRU: visible rows plus margin for
#: scroll-ahead. Cleared on search exit, document swap, and unmount.
_SEARCH_BASE_CACHE_SIZE = 512


class PagerSearchMixin:
    """Implement the search-controller host callbacks."""

    def vim_search_corpus(self: Any) -> str:
        return search_corpus(self.document)

    def vim_search_styled_base(self: Any) -> Text | None:
        surface = self._search_surface()
        return styled_search_base(
            self.document,
            prepared_sections=self._prepared_section_texts(),
            dangling_refs=self._dangling_refs.keys(),
            is_dangling=self._is_target_dangling,
            surface=surface,
        )

    def vim_search_paint_matches(
        self: Any,
        match_spans: tuple[SearchSpan, ...],
        current_index: int | None,
    ) -> None:
        """Paint match offsets lazily, one viewport at a time.

        The controller hands over sorted absolute match spans instead of
        a fully styled copy of the corpus. Only visible rows are
        materialized through :meth:`_search_row_text`; no full-corpus
        ``Text`` is built here.
        """
        spans = tuple(match_spans)
        self._search_match_spans = spans
        self._search_match_starts = [start for start, _end in spans]
        self._search_match_index = current_index
        signature = self._search_base_signature()
        if signature != getattr(self, "_search_base_signature_value", None):
            cache = getattr(self, "_search_base_cache", None)
            if isinstance(cache, LRUCache):
                cache.clear()
            self._search_section_sources: dict[int, Any] = {}
            self._search_base_signature_value = signature
        self._search_ensure_map()
        try:
            scroll = self._body_scroll()
        except Exception:
            return
        try:
            line_count = int(getattr(self, "_search_match_lines", 0) or 0)
        except Exception:
            line_count = 0
        try:
            scroll.set_match_overlay(line_count)
        except Exception:
            try:
                scroll.clear_strip_cache()
            except Exception:
                pass
            try:
                scroll.refresh(layout=True)
            except Exception:
                pass

    def _search_surface(self: Any) -> str | None:
        surface = None
        try:
            styles_fn = getattr(self, "_history_styles", None)
            styles = styles_fn() if callable(styles_fn) else None
            candidate = getattr(styles, "background", None)
            if isinstance(candidate, str) and candidate:
                surface = candidate
        except Exception:
            surface = None
        if surface is None:
            try:
                palette = getattr(self, "_syntax_palette", None)
                candidate = getattr(palette, "background", None)
                if isinstance(candidate, str) and candidate:
                    surface = candidate
            except Exception:
                surface = None
        return surface

    def _search_base_signature(self: Any) -> Any:
        """Return a cheap hashable for everything one base line depends on."""
        try:
            prepared = self._prepared_section_texts()
        except Exception:
            prepared = {}
        try:
            prepared_sig = tuple(
                (index, id(text)) for index, text in sorted(prepared.items())
            )
        except Exception:
            prepared_sig = ()
        try:
            dangling_sig = frozenset(self._dangling_refs.keys())
        except Exception:
            dangling_sig = frozenset()
        try:
            generation = int(getattr(self, "_syntax_generation", 0) or 0)
        except Exception:
            generation = 0
        try:
            document_id = id(getattr(self, "document", None))
        except Exception:
            document_id = 0
        return (
            document_id,
            generation,
            self._search_surface(),
            prepared_sig,
            dangling_sig,
        )

    def _search_ensure_map(self: Any) -> None:
        """Build the corpus-line -> section-line map once per search."""
        if getattr(self, "_search_map", None) is not None:
            return
        sections = getattr(getattr(self, "document", None), "sections", ())
        mapping: list[tuple[str, int, int]] = []
        for section_index, section in enumerate(sections):
            if section_index > 0:
                mapping.append(("rule", section_index, -1))
            try:
                plain = section.plain_text
            except Exception:
                plain = ""
            if not plain:
                mapping.append(("body", section_index, -1))
                continue
            try:
                starts = logical_line_starts(plain)
            except Exception:
                mapping.append(("body", section_index, -1))
                continue
            for line_no in range(len(starts)):
                mapping.append(("body", section_index, line_no))
        self._search_map = mapping
        self._search_match_lines = len(mapping)
        if getattr(self, "_search_base_cache", None) is None:
            self._search_base_cache: LRUCache = LRUCache(
                maxsize=_SEARCH_BASE_CACHE_SIZE
            )
        if getattr(self, "_search_section_sources", None) is None:
            self._search_section_sources = {}
        if getattr(self, "_search_match_spans", None) is None:
            self._search_match_spans = ()
            self._search_match_starts = []
            self._search_match_index = None

    def _search_rule_text(self: Any, section_index: int) -> str:
        sections = getattr(getattr(self, "document", None), "sections", ())
        total = len(sections)
        try:
            title = sections[section_index].title
        except Exception:
            title = ""
        return f"── {section_index + 1}/{total} · {title} ──"

    def _search_section_styled(self: Any, section_index: int) -> Any | None:
        """Return the target-accented section text, cached per signature."""
        sources = getattr(self, "_search_section_sources", None)
        if sources is None:
            sources = {}
            self._search_section_sources = sources
        cached = sources.get(section_index)
        if cached is not None:
            return cached
        sections = getattr(getattr(self, "document", None), "sections", ())
        if section_index < 0 or section_index >= len(sections):
            return None
        section = sections[section_index]
        try:
            prepared = self._prepared_section_texts()
        except Exception:
            prepared = {}
        base = prepared.get(section_index)
        if base is None:
            try:
                base = section.body_text
            except Exception:
                return None
        else:
            base = base.copy()
        try:
            styled = style_target_accents(
                base,
                section,
                section_index,
                self.document.origin,
                dangling_refs=self._dangling_refs.keys(),
                is_dangling=self._is_target_dangling,
                surface=self._search_surface(),
            )
        except Exception:
            return None
        try:
            index = build_span_index(styled)
            starts = logical_line_starts(styled.plain)
        except Exception:
            return None
        entry = (styled, index, starts)
        # Bound: one entry per section; documents hold few sections.
        sources[section_index] = entry
        return entry

    def _search_base_line(self: Any, row: int) -> Text:
        """Return corpus line *row* with syntax and target accents, no matches."""
        mapping = getattr(self, "_search_map", None) or ()
        if row < 0 or row >= len(mapping):
            return Text("")
        cache = getattr(self, "_search_base_cache", None)
        if cache is None:
            cache = LRUCache(maxsize=_SEARCH_BASE_CACHE_SIZE)
            self._search_base_cache = cache
        try:
            cached = cache.get(row)
        except Exception:
            cached = None
        if cached is not None:
            return cached.copy()
        kind, section_index, line_no = mapping[row]
        if kind == "rule":
            base = Text(self._search_rule_text(section_index))
        elif line_no < 0:
            base = Text("")
        else:
            entry = self._search_section_styled(section_index)
            if entry is None:
                base = Text("")
            else:
                styled, index, starts = entry
                if line_no < 0 or line_no >= len(starts):
                    base = Text("")
                else:
                    try:
                        end = logical_line_end(starts, line_no, styled.plain)
                        base = slice_styled_line(
                            styled, starts[line_no], end, index=index
                        )
                    except Exception:
                        base = Text("")
        base.no_wrap = True
        base.overflow = "crop"
        try:
            cache[row] = base.copy()
        except Exception:
            pass
        try:
            self._search_base_lines_built = (
                int(getattr(self, "_search_base_lines_built", 0) or 0) + 1
            )
        except Exception:
            pass
        return base

    def _search_row_text(self: Any, row: int) -> Text:
        """Return corpus line *row* with match and current-match styles."""
        try:
            base = self._search_base_line(row).copy()
        except Exception:
            base = Text("")
        try:
            search = getattr(self, "_search", None)
            line_starts = (
                getattr(search, "line_starts", None) if search is not None else None
            )
            corpus = getattr(search, "corpus", "") if search is not None else ""
            if line_starts and 0 <= row < len(line_starts) - 1:
                line_start = int(line_starts[row])
                line_end = int(line_starts[row + 1]) - 1
                if line_end < line_start:
                    line_end = line_start
                corpus_end = len(corpus) if isinstance(corpus, str) else line_end
                line_end = min(line_end, corpus_end)
            else:
                line_start = -1
                line_end = -1
            spans = tuple(getattr(self, "_search_match_spans", ()) or ())
            starts = list(getattr(self, "_search_match_starts", None) or [])
            if len(starts) != len(spans):
                starts = [start for start, _end in spans]
            current_index = getattr(self, "_search_match_index", None)
            if line_start >= 0 and spans:
                lo = bisect_left(starts, line_start)
                while lo > 0 and spans[lo - 1][1] > line_start:
                    lo -= 1
                position = lo
                while position < len(spans) and spans[position][0] < line_end:
                    start, end = spans[position]
                    if end > line_start and end > start:
                        base.stylize(
                            MATCH_STYLE,
                            max(start, line_start) - line_start,
                            min(end, line_end) - line_start,
                        )
                    position += 1
                if isinstance(current_index, int) and 0 <= current_index < len(spans):
                    start, end = spans[current_index]
                    if start < line_end and end > line_start and end > start:
                        base.stylize(
                            CURRENT_MATCH_STYLE,
                            max(start, line_start) - line_start,
                            min(end, line_end) - line_start,
                        )
        except Exception:
            pass
        try:
            self._search_rows_painted = (
                int(getattr(self, "_search_rows_painted", 0) or 0) + 1
            )
        except Exception:
            pass
        return base

    def vim_search_origin_scroll(self: Any) -> tuple[int, int]:
        scroll = self._body_scroll()
        return (int(scroll.scroll_x), int(scroll.scroll_y))

    def vim_search_overlay_viewport(self: Any) -> SearchViewport:
        scroll = self._body_scroll()
        region = scroll.scrollable_content_region
        return SearchViewport(
            scroll_x=int(scroll.scroll_x),
            scroll_y=int(scroll.scroll_y),
            width=region.width,
            height=region.height,
        )

    def vim_search_started(self: Any) -> None:
        """No live refresh source to pause: the document is immutable."""

    def vim_search_exited(self: Any, *, refresh: bool) -> None:
        """The body is already restored by ``vim_search_hide_overlay``."""

    def vim_search_show_overlay(self: Any) -> None:
        self._search_match_spans = ()
        self._search_match_starts = []
        self._search_match_index = None
        self._search_map = None
        self._search_match_lines = 0
        self._search_base_cache = LRUCache(maxsize=_SEARCH_BASE_CACHE_SIZE)
        self._search_section_sources = {}
        self._search_base_signature_value = self._search_base_signature()
        self._search_base_lines_built = 0
        self._search_rows_painted = 0
        self.query_one("#pager-search-command", Static).remove_class("hidden")

    def vim_search_hide_overlay(self: Any) -> None:
        self._search_match_spans = ()
        self._search_match_starts = []
        self._search_match_index = None
        self._search_map = None
        self._search_match_lines = 0
        self._search_base_signature_value = None
        try:
            cache = getattr(self, "_search_base_cache", None)
            if isinstance(cache, LRUCache):
                cache.clear()
        except Exception:
            pass
        self._search_section_sources = {}
        try:
            self._body_scroll().clear_match_overlay()
        except Exception:
            pass
        try:
            self._body_scroll().set_overlay(None)
        except Exception:
            pass
        command = self.query_one("#pager-search-command", Static)
        command.update("")
        command.add_class("hidden")

    def vim_search_paint_overlay(self: Any, content: Text) -> None:
        self._body_scroll().set_overlay(content)

    def vim_search_command_width(self: Any) -> int:
        command = self.query_one("#pager-search-command", Static)
        return max(0, int(command.size.width) - 2)

    def vim_search_paint_command_line(
        self: Any,
        content: Text,
        mode: VimSearchMode,
    ) -> None:
        command = self.query_one("#pager-search-command", Static)
        command.update(content)
        command.remove_class("hidden")

    def vim_search_scroll_overlay(self: Any, *, x: int, y: int) -> None:
        self._body_scroll().scroll_to(x=x, y=y, animate=False, immediate=True)
        self._update_chrome_position()

    def vim_search_restore_scroll(self: Any, *, x: int, y: int) -> None:
        def restore() -> None:
            self._body_scroll().scroll_to(x=x, y=y, animate=False, immediate=True)
            self._update_chrome_position()

        self.call_after_refresh(restore)

    def vim_search_focus_overlay(self: Any) -> None:
        self.call_after_refresh(self._body_scroll().focus)

    def vim_search_focus_native(self: Any) -> None:
        self.call_after_refresh(self._body_scroll().focus)

    def vim_search_notify(self: Any, message: str) -> None:
        self.notify(message, severity="information")


__all__ = ["PagerSearchMixin"]
