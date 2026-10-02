"""Fold expansion for the ``PagerScreen`` diff views.

Owns in-place fold expansion through jump labels and the caller-owned
document fold branch. View toggling and rendering live in
``_screen_diff_view``; change navigation lives in
``_screen_diff_navigate``; this module never imports those siblings.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sase.pager.document import PagerSection
from sase.pager.history.diff import FOLD_TARGET_KIND, build_diff_body

__all__ = ["PagerDiffFoldsMixin"]


class PagerDiffFoldsMixin:
    """Expand diff and document folds in place."""

    document: Any
    _body: Any | None
    _body_width: int | None
    _label_layer: Any | None
    _history_states: dict[str, Any]

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
            styles_fn = getattr(self, "_history_styles", None)
            styles = styles_fn() if callable(styles_fn) else None
            rendered = build_diff_body(
                comparison,
                read_section.plain_text,
                expanded=frozenset(state.expanded_folds),
                history_styles=styles,
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
