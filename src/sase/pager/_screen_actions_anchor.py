"""Same-document anchor follows for ``PagerScreen``.

Owns ``_activate_local_anchor`` and its in-place landing. Label dispatch
and section/target actions live in the sibling ``_screen_actions_*``
modules; this module never imports them.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from sase.pager.document import section_local_anchor_lines

__all__ = ["PagerActionAnchorMixin"]


class PagerActionAnchorMixin:
    """Follow ``[text](#heading)`` links inside the current section."""

    def _activate_local_anchor(
        self: Any, section_index: int, fragment: str, action: str
    ) -> None:
        if not 0 <= section_index < len(self.document.sections):
            return
        section = self.document.sections[section_index]
        landed = section_local_anchor_lines(section, fragment)
        if landed is None:
            decoded = unquote(fragment or "")
            self.notify(
                f"No heading or anchor matches #{decoded} in {section.title}.",
                severity="warning",
            )
            if action == "other":
                try:
                    self.pager_host._disarm_other()  # type: ignore[attr-defined]
                except Exception:
                    pass
            return
        start, end = landed
        if action == "other":
            self._show_document_in_other_view(
                self.document, start, end, section_index=section_index
            )
            return
        if action == "edit":
            self._edit_local_anchor(section_index, start)
            return
        self._land_local_anchor(section_index, start, end)

    def _land_local_anchor(self: Any, section_index: int, start: int, end: int) -> None:
        self._resolve_generation += 1
        self._set_footer_status(None)
        mark = self._line_mark_for_landing(
            line=start, end_line=end, section_index=section_index
        )
        if mark is None:
            self.notify("Nothing to jump to.", severity="information")
            return
        self._push_trail_entry()
        self._forward_trail.clear()
        self._goto_mark = mark
        self._invalidate_body_paint()
        self._scroll_to_line_mark(mark)
        self._after_scroll()
        self._update_trail()
        self._update_footer()
        self._update_subject()

    def _edit_local_anchor(self: Any, section_index: int, start: int) -> None:
        section = self.document.sections[section_index]
        pin = getattr(section, "version_pin", None)
        pinned_ordinal = int(getattr(pin, "ordinal", 0) or 0) if pin is not None else 0
        edit_line: int | None = None if pinned_ordinal > 0 else start
        live_path = self._history_live_path_for_section(section)
        if live_path is not None:
            if live_path == "__deleted__":
                self.notify(
                    "This version was deleted — no live file to edit.",
                    severity="warning",
                )
                return
            context = self._link_context_for_section_index(section_index)
            owner = section.owner
            if owner is not None and context is not None:
                from dataclasses import replace as _replace

                from sase.pager.link_context import merge_link_context

                unpinned = _replace(owner, revision=None)
                context = merge_link_context(
                    section.link_anchors,
                    self.document.link_context,
                    owner=unpinned,
                )
            self._resolve_and_dispatch(
                live_path,
                intent="edit",
                context=context,
                edit_line=edit_line,
            )
            return
        ref = section.subject_ref
        if ref is None:
            self.notify("This section has nothing to edit.", severity="warning")
            return
        self._resolve_and_dispatch(
            ref,
            intent="edit",
            context=self._link_context_for_section_index(section_index),
            edit_line=edit_line,
        )
