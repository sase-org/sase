"""Read/diff view toggle, change navigation, and fold expansion.

Owns the ``=`` view toggle, ``[``/``]`` change jumps in both views,
in-place fold expansion through jump labels, and the ``yy`` unified-diff
copy branch for ``PagerScreen`` history sections. Version-step, discovery,
and gutter-mark logic stays in ``_screen_history``; word-diff rendering
stays in ``pager.history.diff``.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.pager._labels import PagerLabelLayer
from sase.pager._layout import ComposedBody
from sase.pager._line_mark import reading_scroll_y
from sase.pager.document import PagerSection
from sase.pager.history.diff import (
    FOLD_TARGET_KIND,
    build_diff_body,
    diff_endpoints,
    read_view_change_lines,
    unified_diff_for_comparison,
)
from sase.pager.history.models import HistoryView

_HISTORY_TASK_ATTR = "_pump_free_history_tasks"
_HISTORY_CACHE_LIMIT = 50


class PagerDiffMixin:
    """Own the history diff view and change navigation for one screen."""

    document: Any
    _body: ComposedBody | None
    _body_width: int | None
    _label_layer: PagerLabelLayer | None
    _history_states: dict[str, Any]
    _history_generation: int
    _history_supported: dict[str, bool]
    _history_view_sticky: HistoryView | None

    def _init_diff_state(self: Any) -> None:
        self._history_view_sticky = None

    def _effective_view(self: Any, section: PagerSection, state: Any) -> HistoryView:
        if self._history_view_sticky is not None:
            return self._history_view_sticky
        pin = state.current_pin if state is not None else None
        if pin is None:
            pin = section.version_pin
        if getattr(pin, "view", "read") == "diff":
            return "diff"
        return "read"

    def _current_ordinal(self: Any, section: PagerSection, state: Any) -> int:
        pin = state.current_pin if state is not None else None
        if pin is None:
            pin = section.version_pin
        return int(getattr(pin, "ordinal", 0) or 0)

    def _diff_endpoints_for(
        self: Any, section: PagerSection, state: Any
    ) -> tuple[int, int] | None:
        pin = state.current_pin if state is not None else None
        if pin is None:
            pin = section.version_pin
        ordinal = int(getattr(pin, "ordinal", 0) or 0)
        compare_base = getattr(pin, "compare_base", None)
        try:
            base_override = int(compare_base) if compare_base is not None else None
        except (TypeError, ValueError):
            base_override = None
        return diff_endpoints(
            ordinal=ordinal,
            visible_ordinals=tuple(state.visible_ordinals) if state is not None else (),
            dirty=bool(state is not None and state.status == "dirty-now"),
            compare_base=base_override,
        )

    def action_history_toggle_diff(self: Any) -> None:
        """Switch the current section between the read and diff views."""
        try:
            section = self._current_section()
        except Exception:
            return
        identity = section.identity
        state = self._history_states.get(identity)
        if state is None:
            if self._history_supported.get(identity) is False:
                self.notify("No history for this section.", severity="information")
                return
            # Discovery in flight: queue the toggle like version steps do.
            self._history_pending[identity] = "toggle-diff"
            self._start_history_discovery_after_paint()
            return
        self._toggle_diff_for_state(identity)

    def _toggle_diff_for_state(self: Any, identity: str) -> None:
        """Flip the diff view once history state for *identity* exists."""
        state = self._history_states.get(identity)
        if state is None:
            return
        try:
            section = next(s for s in self.document.sections if s.identity == identity)
        except StopIteration:
            return
        if not state.visible_ordinals:
            self.notify("No committed versions.", severity="information")
            return
        current = self._effective_view(section, state)
        switch: HistoryView = "read" if current == "diff" else "diff"
        # An explicit `=` sticks for the rest of the pager session.
        self._history_view_sticky = switch
        if switch == "read":
            self._apply_read_view(identity)
        else:
            self._ensure_diff_view(identity)

    def action_history_prev_change(self: Any) -> None:
        """Jump to the previous change in either view."""
        self._jump_to_change(-1)

    def action_history_next_change(self: Any) -> None:
        """Jump to the next change in either view."""
        self._jump_to_change(1)

    def _apply_read_view(self: Any, identity: str) -> None:
        state = self._history_states.get(identity)
        if state is None:
            return
        ordinal = self._history_current_pin_ordinal_for_identity(identity)
        read_section: PagerSection | None = None
        if ordinal == 0:
            live = getattr(state, "live_section", None)
            if isinstance(live, PagerSection):
                read_section = live
        else:
            cached = state.body_cache.get((ordinal, state.subject_id))
            if isinstance(cached, PagerSection):
                read_section = cached
        if read_section is None:
            task = spawn_pump_free_task(
                self,
                self._load_and_swap_version(
                    identity, ordinal, self.document, self._history_generation
                ),
                name="sase-pager-history-step",
                registry_attr=_HISTORY_TASK_ATTR,
            )
            if task is None:
                self.notify("History worker unavailable.", severity="warning")
            return
        self._swap_active_section(read_section, ordinal, self._history_generation)

    def _ensure_diff_view(self: Any, identity: str) -> None:
        state = self._history_states.get(identity)
        if state is None:
            return
        try:
            section = next(s for s in self.document.sections if s.identity == identity)
        except StopIteration:
            return
        endpoints = self._diff_endpoints_for(section, state)
        if endpoints is None:
            self.notify("No committed versions.", severity="information")
            return
        base, target = endpoints
        comparison = state.comparison_cache.get((base, target))
        if not isinstance(comparison, dict):
            comparison = None
        read_section = self._diff_read_section(identity, state, target)
        if comparison is not None and read_section is not None:
            self._apply_diff_view(identity, base, target, comparison)
            return
        self._set_footer_status("loading diff")
        task = spawn_pump_free_task(
            self,
            self._fetch_and_apply_diff(
                identity, base, target, self.document, self._history_generation
            ),
            name="sase-pager-history-diff",
            registry_attr=_HISTORY_TASK_ATTR,
        )
        if task is None:
            self._set_footer_status(None)
            self.notify("History worker unavailable.", severity="warning")

    async def _fetch_and_apply_diff(
        self: Any,
        identity: str,
        base: int,
        target: int,
        document: Any,
        generation: int,
    ) -> None:
        state = self._history_states.get(identity)
        if state is None:
            return

        def _fetch() -> tuple[dict[str, Any] | None, Any | None]:
            try:
                section = next(s for s in document.sections if s.identity == identity)
            except StopIteration:
                return (None, None)
            try:
                from sase.pager.history.provider import history_provider_for_section
            except Exception:
                return (None, None)
            try:
                provider = history_provider_for_section(section)
            except Exception:
                return (None, None)
            if provider is None:
                return (None, None)
            try:
                comparison = provider.compare_versions(section, base, target)
            except Exception:
                comparison = None
            body: Any | None = None
            if target > 0:
                try:
                    body = provider.load_version(section, target)
                except Exception:
                    body = None
            return (comparison, body)

        comparison, body = await asyncio.to_thread(_fetch)
        if generation != self._history_generation or self.document is not document:
            return
        self._set_footer_status(None)
        if not isinstance(comparison, dict):
            self.notify("Diff load failed — keeping read view.", severity="warning")
            return
        if len(state.comparison_cache) >= _HISTORY_CACHE_LIMIT:
            state.comparison_cache.clear()
        state.comparison_cache[(base, target)] = comparison
        if isinstance(body, PagerSection) and target > 0:
            if len(state.body_cache) >= _HISTORY_CACHE_LIMIT:
                state.body_cache.clear()
            state.body_cache[(target, state.subject_id)] = body
        try:
            self._recompose_for_history_marks()
        except Exception:
            pass
        self._apply_diff_view(identity, base, target, comparison)

    def _diff_read_section(
        self: Any, identity: str, state: Any, target: int
    ) -> PagerSection | None:
        if target == 0:
            live = getattr(state, "live_section", None)
            if isinstance(live, PagerSection):
                return live
            try:
                current = next(
                    s for s in self.document.sections if s.identity == identity
                )
            except StopIteration:
                return None
            pin = getattr(current, "version_pin", None)
            if pin is None or getattr(pin, "view", "read") == "read":
                return current
            return None
        cached = state.body_cache.get((target, state.subject_id))
        if isinstance(cached, PagerSection):
            return cached
        return None

    def _apply_diff_view(
        self: Any, identity: str, base: int, target: int, comparison: dict[str, Any]
    ) -> None:
        state = self._history_states.get(identity)
        if state is None:
            return
        read_section = self._diff_read_section(identity, state, target)
        if read_section is None:
            self.notify("Diff load failed — keeping read view.", severity="warning")
            return
        # Keep the current ordinal: at a clean now the diff renders the
        # newest version's change against the live body, but the pin must
        # stay on now so the chrome never claims the past unprompted.
        pin = state.current_pin
        if pin is None:
            pin = read_section.version_pin
        if pin is None:
            from sase.pager.history.models import live_pin_for_subject

            pin = live_pin_for_subject(state.subject_id)
        try:
            new_pin = replace(pin, view="diff", compare_base=base if base > 0 else None)
        except Exception:
            return
        try:
            rendered = build_diff_body(
                comparison,
                read_section.plain_text,
                expanded=frozenset(state.expanded_folds),
            )
        except Exception:
            self.notify("Diff render failed — keeping read view.", severity="warning")
            return
        try:
            index = next(
                i
                for i, s in enumerate(self.document.sections)
                if s.identity == identity
            )
        except StopIteration:
            return
        try:
            diff_section = replace(
                read_section,
                body=rendered.text,
                targets=rendered.fold_targets,
                version_pin=new_pin,
            )
        except ValueError as exc:
            self.notify(f"Diff render failed — {exc}", severity="warning")
            return
        state.current_pin = new_pin
        sections = list(self.document.sections)
        sections[index] = diff_section
        self.document = replace(self.document, sections=tuple(sections))
        self._body = None
        self._body_width = None
        self._label_layer = None
        self._ensure_body()
        try:
            if self._search.is_active and self._search.query:
                self._reapply_history_search(self._search.query, self._search.direction)
            elif self._search.is_active:
                self._search.refresh_styled_base()
        except Exception:
            pass
        self._set_footer_status(None)
        self._update_footer()
        self._update_subject()
        try:
            self._schedule_syntax_preparation()
        except Exception:
            pass

    def _diff_unified_for_section(self: Any, section: Any) -> tuple[bool, bool, str]:
        """Return ``(is_diff_view, ready, unified_text)`` for ``yy``.

        *ready* is false while the comparison is still loading; a ready
        but empty text means core recorded no unified diff.
        """
        pin = getattr(section, "version_pin", None)
        if pin is None or getattr(pin, "view", "read") != "diff":
            return (False, False, "")
        state = self._history_states.get(section.identity)
        if state is None:
            return (True, False, "")
        endpoints = self._diff_endpoints_for(section, state)
        if endpoints is None:
            return (True, False, "")
        base, target = endpoints
        comparison = state.comparison_cache.get((base, target))
        if not isinstance(comparison, dict):
            return (True, False, "")
        return (True, True, unified_diff_for_comparison(comparison))

    def _jump_to_change(self: Any, direction: int) -> None:
        try:
            section = self._current_section()
        except Exception:
            return
        identity = section.identity
        state = self._history_states.get(identity)
        if state is None:
            if self._history_supported.get(identity) is False:
                self.notify("No history for this section.", severity="information")
                return
            self.notify("History still loading — try again.", severity="information")
            self._start_history_discovery_after_paint()
            return
        if self._effective_view(section, state) == "diff":
            lines = self._diff_change_lines(identity, section, state)
        else:
            lines = self._read_change_lines(identity, section, state)
        if lines is None:
            return
        if not lines:
            if self._current_ordinal(section, state) <= 0:
                self.notify(
                    "Open a past version to walk its changes.",
                    severity="information",
                )
            else:
                self.notify("No changes in this version.", severity="information")
            return
        try:
            index = next(
                i
                for i, s in enumerate(self.document.sections)
                if s.identity == identity
            )
        except StopIteration:
            return
        current = self._current_body_line(index)
        if direction < 0:
            candidates = [line for line in lines if line < current]
            if not candidates:
                self.notify("Already at the first change.", severity="information")
                return
            goal = max(candidates)
        else:
            candidates = [line for line in lines if line > current]
            if not candidates:
                self.notify("Already at the last change.", severity="information")
                return
            goal = min(candidates)
        self._scroll_to_body_line(index, goal)

    def _read_change_lines(
        self: Any, identity: str, section: PagerSection, state: Any
    ) -> tuple[int, ...] | None:
        ordinal = self._current_ordinal(section, state)
        if ordinal <= 0:
            return ()
        comparison = state.comparison_cache.get((ordinal - 1, ordinal))
        if comparison is None:
            comparison = state.comparison_cache.get((0, ordinal))
        if not isinstance(comparison, dict):
            task = spawn_pump_free_task(
                self,
                self._load_one_comparison(
                    identity,
                    ordinal - 1,
                    ordinal,
                    self.document,
                    self._history_generation,
                ),
                name="sase-pager-history-compare",
                registry_attr=_HISTORY_TASK_ATTR,
            )
            if task is None:
                self.notify("History worker unavailable.", severity="warning")
            else:
                self.notify("Loading changes — press again.", severity="information")
            return None
        return read_view_change_lines(comparison)

    def _diff_change_lines(
        self: Any, identity: str, section: PagerSection, state: Any
    ) -> tuple[int, ...] | None:
        endpoints = self._diff_endpoints_for(section, state)
        if endpoints is None:
            return ()
        base, target = endpoints
        comparison = state.comparison_cache.get((base, target))
        if not isinstance(comparison, dict):
            self._ensure_diff_view(identity)
            self.notify("Loading diff — press again.", severity="information")
            return None
        read_section = self._diff_read_section(identity, state, target)
        if read_section is None:
            return ()
        try:
            rendered = build_diff_body(
                comparison,
                read_section.plain_text,
                expanded=frozenset(state.expanded_folds),
            )
        except Exception:
            return ()
        return rendered.change_lines

    def _current_body_line(self: Any, section_index: int) -> int:
        try:
            body = self._body
            scroll = self._body_scroll()
            if body is None:
                return 1
            section_offset = body.section_offsets[section_index]
            top = max(int(scroll.scroll_y) - section_offset, 0)
            rows = body.section_line_rows[section_index]
            line = 1
            for number, row in enumerate(rows, start=1):
                if row <= top:
                    line = number
                else:
                    break
            return line
        except Exception:
            return 1

    def _scroll_to_body_line(self: Any, section_index: int, line: int) -> None:
        try:
            body = self._body
            scroll = self._body_scroll()
            if body is None:
                return
            rows = body.section_line_rows[section_index]
            if not rows:
                return
            clamped = max(1, min(line, len(rows)))
            start_row = rows[clamped - 1]
            if clamped < len(rows):
                end_row = rows[clamped] - 1
            elif section_index + 1 < len(body.section_offsets):
                end_row = body.section_offsets[section_index + 1] - 1
            else:
                end_row = max(body.total_height - 1, start_row)
            viewport = max(int(scroll.size.height), 1)
            goal = reading_scroll_y(
                start_row=start_row,
                end_row=max(end_row, start_row),
                viewport_height=viewport,
                max_scroll_y=scroll.max_scroll_y,
            )
            scroll.scroll_to(y=goal, animate=False, immediate=True)
            self._after_scroll()
        except Exception:
            pass

    def _activate_label(self: Any, label: Any) -> None:
        target = label.target
        if (
            getattr(target, "kind", None) == FOLD_TARGET_KIND
            and getattr(target, "source", None) == "attached"
            and isinstance(getattr(target, "target", None), int)
            and not isinstance(getattr(target, "target", None), bool)
        ):
            self._pending_action = "follow"
            self._label_pending_prefix = ""
            self._expand_history_fold(label.section_index, int(target.target))
            return
        super()._activate_label(label)  # type: ignore[misc]

    def _expand_history_fold(self: Any, section_index: int, fold_index: int) -> None:
        try:
            section = self.document.sections[section_index]
        except IndexError:
            return
        state = self._history_states.get(section.identity)
        if state is None:
            self._expand_document_fold(section_index, fold_index)
            return
        if fold_index in state.expanded_folds:
            return
        pin = state.current_pin or section.version_pin
        if getattr(pin, "view", "read") != "diff":
            return
        state.expanded_folds.add(fold_index)
        endpoints = self._diff_endpoints_for(section, state)
        if endpoints is None:
            state.expanded_folds.discard(fold_index)
            return
        base, target = endpoints
        comparison = state.comparison_cache.get((base, target))
        read_section = self._diff_read_section(section.identity, state, target)
        if not isinstance(comparison, dict) or read_section is None:
            state.expanded_folds.discard(fold_index)
            return
        try:
            rendered = build_diff_body(
                comparison,
                read_section.plain_text,
                expanded=frozenset(state.expanded_folds),
            )
            replacement = replace(
                read_section,
                body=rendered.text,
                targets=rendered.fold_targets,
                version_pin=pin,
            )
        except (ValueError, TypeError):
            state.expanded_folds.discard(fold_index)
            return
        anchor = self._capture_history_anchor(section_index)
        sections = list(self.document.sections)
        sections[section_index] = replacement
        self.document = replace(self.document, sections=tuple(sections))
        self._body = None
        self._body_width = None
        self._label_layer = None
        self._ensure_body()
        self._restore_history_anchor(section_index, replacement, anchor)
        self._update_footer()
        self._update_subject()
        try:
            self._schedule_syntax_preparation()
        except Exception:
            pass

    def _expand_document_fold(self: Any, section_index: int, fold_index: int) -> None:
        """Expand a caller-owned fold (e.g. a feed regen-only group).

        Documents such as the memory changes feed carry their own
        ``expand_fold_fn`` hook that recomposes one section in place.
        Like diff folds this pushes no trail entry; unlike them it needs
        no history state.
        """
        expander = getattr(self.document, "expand_fold_fn", None)
        if expander is None:
            return
        try:
            section = self.document.sections[section_index]
        except IndexError:
            return
        try:
            replacement = expander(section.identity, fold_index)
        except Exception:
            return
        if replacement is None or not isinstance(replacement, PagerSection):
            return
        if replacement.identity != section.identity:
            return
        anchor = self._capture_history_anchor(section_index)
        sections = list(self.document.sections)
        sections[section_index] = replacement
        self.document = replace(self.document, sections=tuple(sections))
        self._body = None
        self._body_width = None
        self._label_layer = None
        self._ensure_body()
        self._restore_history_anchor(section_index, replacement, anchor)
        self._update_footer()
        self._update_subject()
        try:
            self._schedule_syntax_preparation()
        except Exception:
            pass


__all__ = ["PagerDiffMixin"]
