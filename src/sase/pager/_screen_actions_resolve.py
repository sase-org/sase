"""Async resolve dispatch and navigation for ``PagerScreen``.

Owns ``_resolve_and_dispatch`` and its historical/apply helpers plus
document navigation and the dangling-ref and link-context helpers. Label
handling and section/target actions live in the sibling
``_screen_actions_*`` modules; this module never imports them.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.pager._body_layout import BodyLayout
from sase.pager._body_rows import BodyRenderer
from sase.pager._labels import LabelWindowScope, PagerLabel, PagerLabelLayer
from sase.pager.app import ViewPendingAction
from sase.pager.document import (
    PagerDocument,
    PagerOrigin,
    PagerTargetSpan,
    section_origin,
    target_resolution_cache_identity,
)
from sase.pager.link_context import LinkResolutionContext, merge_link_context
from sase.pager.owner import owner_cache_key
from sase.pager.resolve import (
    LinkResolution,
    LinkTarget,
    LinkTargetKind,
)

__all__ = ["DanglingRefKey", "PagerActionResolveMixin"]

#: Key for the dangling (unresolvable) reference notice cache. Public so
#: the view that owns the cache can annotate it without importing a
#: private name across modules.
DanglingRefKey = tuple[
    object,
    tuple[tuple[Path, int | None], ...],
    object,
]


class PagerActionResolveMixin:
    """Resolve link destinations and navigate to the results."""

    _body: BodyLayout | None
    _body_renderer: BodyRenderer | None
    _label_layer: PagerLabelLayer | None
    _label_window_scope: LabelWindowScope | None
    _last_activated_label: PagerLabel | None
    _pending_action: ViewPendingAction
    _dangling_refs: dict[DanglingRefKey, str]

    def _show_document_in_other_view(
        self: Any,
        document: PagerDocument,
        line: int | None,
        end_line: int | None = None,
    ) -> None:
        """Open *document* in the other pane, leaving focus on this view."""
        self.pager_host.show_in_other_view(self, document, line, end_line)

    def _resolve_and_dispatch(
        self: Any,
        ref: str,
        *,
        intent: Literal["follow", "edit"],
        context: LinkResolutionContext | None = None,
        cache_identity: object | None = None,
        other_pane: bool = False,
    ) -> None:
        key = self._dangling_ref_key(cache_identity or ref, context)
        cached = self._dangling_refs.get(key)
        if cached is not None:
            self.notify(cached, severity="warning")
            return
        self._set_footer_status("loading")
        self._resolve_generation += 1
        # An other-pane follow leaves this pane where it is, so its in-flight
        # history discovery/steps must survive; the host bumps whichever
        # pane actually navigates.
        history_bump = getattr(self, "_bump_history_generation", None)
        if callable(history_bump) and not other_pane:
            history_bump()
        generation = self._resolve_generation
        document = self.document
        try:
            history_section = self._current_section()
        except Exception:
            history_section = None

        async def resolve_task() -> None:
            if (
                history_section is not None
                and getattr(history_section, "version_pin", None) is not None
            ):
                historical = await asyncio.to_thread(
                    self._try_historical_link, history_section, ref
                )
                try:
                    if not self.is_mounted:
                        return
                except Exception:
                    pass
                if (
                    generation != self._resolve_generation
                    or self.document is not document
                ):
                    return
                if historical is not None:
                    self._apply_historical_section(
                        historical,
                        ref,
                        intent=intent,
                        context=context,
                        other_pane=other_pane,
                    )
                    return
                if getattr(self, "_history_miss_notice", None) is not None:
                    notice = self._history_miss_notice  # type: ignore[attr-defined]
                    self._history_miss_notice = None  # type: ignore[attr-defined]
                    if notice:
                        self._set_footer_status(None)
                        self.notify(notice, severity="warning")
                        self._repaint_label_state()
                        return
            try:
                result = await asyncio.to_thread(
                    self._resolve_ref,
                    ref,
                    context=context,
                )
            except Exception as exc:  # noqa: BLE001 - a press must never crash the pager
                try:
                    if not self.is_mounted:
                        return
                except Exception:
                    pass
                if generation == self._resolve_generation and self.document is document:
                    self._set_footer_status(None)
                    self.notify(f"Could not resolve {ref} - {exc}", severity="error")
                return
            try:
                if not self.is_mounted:
                    return
            except Exception:
                pass
            if generation != self._resolve_generation or self.document is not document:
                return
            self._apply_resolution(
                ref,
                result,
                intent=intent,
                context=context,
                cache_identity=cache_identity,
                other_pane=other_pane,
            )

        spawn_pump_free_task(
            self,
            resolve_task(),
            name="sase-pager-resolve",
            registry_attr="_pump_free_resolve_tasks",
        )

    def _try_historical_link(self: Any, section: Any, ref: str) -> Any | None:
        try:
            from sase.pager.history.provider import history_provider_for_section
        except Exception:
            return None
        try:
            provider = history_provider_for_section(section)
        except Exception:
            return None
        if provider is None:
            return None
        try:
            resolve = getattr(provider, "resolve_historical_link", None)
            if resolve is None:
                return None
            return resolve(section, ref)
        except Exception as exc:
            try:
                from sase.pager.history.provider import HistoryMissingError as _Miss

                if isinstance(exc, _Miss):
                    pin = getattr(section, "version_pin", None)
                    commit = str(getattr(pin, "commit", "") or "")[:7]
                    self._history_miss_notice = (  # type: ignore[attr-defined]
                        f"{ref} is not present at {commit}; "
                        "open at creation or now instead."
                    )
                    return None
            except Exception:
                pass
            try:
                if "HistoryMissingError" in type(exc).__name__:
                    self._history_miss_notice = str(exc)  # type: ignore[attr-defined]
                    return None
            except Exception:
                pass
            return None

    def _apply_historical_section(
        self: Any,
        section: Any,
        ref: str,
        *,
        intent: str,
        context: Any | None = None,
        other_pane: bool = False,
    ) -> None:
        try:
            if not self.is_mounted:
                return
        except Exception:
            pass
        from sase.pager.document import PagerDocument

        self._set_footer_status(None)
        if intent == "edit":
            self._dispatch_section_action("edit")
            return
        document = PagerDocument(
            sections=(section,),
            title=section.title,
            origin=self.document.origin,
            link_context=self.document.link_context,
        )
        if other_pane:
            self._show_document_in_other_view(document, line=None)
            return
        self._push_trail_entry()
        self._navigate_to_document(document, line=None)

    def _apply_resolution(
        self: Any,
        ref: str,
        result: LinkResolution | LinkTarget | None,
        *,
        intent: Literal["follow", "edit"],
        context: LinkResolutionContext | None = None,
        cache_identity: object | None = None,
        other_pane: bool = False,
    ) -> None:
        try:
            if not self.is_mounted:
                return
        except Exception:
            pass
        self._set_footer_status(None)
        resolution = _as_link_resolution(result)
        target = resolution.target
        if target is None:
            message = resolution.unresolved_message or f"{ref} could not be resolved."
            if not resolution.retryable:
                self._dangling_refs[
                    self._dangling_ref_key(cache_identity or ref, context)
                ] = message
            self.notify(message, severity="warning")
            if resolution.retryable:
                self._repaint_label_state()
            else:
                # A new dangling mark changes the label set, so relabel
                # the layout instead of repainting the stale layer.
                self._invalidate_body_layout(relabel=True)
                self._update_footer()
            return
        if intent == "edit":
            self._launch_editor(target)
            return
        if target.kind is LinkTargetKind.MEDIA:
            self._show_media(target)
            return
        if target.document is not None:
            if other_pane:
                self._show_document_in_other_view(
                    target.document,
                    target.scroll_line,
                    target.scroll_end_line,
                )
                return
            self._push_trail_entry()
            self._navigate_to_document(
                target.document,
                line=target.scroll_line,
                end_line=target.scroll_end_line,
            )

    def _navigate_to_document(
        self: Any,
        document: PagerDocument,
        *,
        line: int | None,
        end_line: int | None = None,
    ) -> None:
        self.document = document
        self._body = None
        self._body_renderer = None
        self._label_layer = None
        self._label_pending_prefix = ""
        self._label_window_scope = None
        self._last_activated_label = None
        self._pending_action = "follow"
        self._clear_goto_state()
        self._reset_search_state()
        self._reset_syntax_for_new_document()
        self._invalidate_body_layout()
        scroll = self._body_scroll()
        scroll.scroll_to(x=0, y=0, animate=False, immediate=True)
        mark = self._line_mark_for_landing(line=line, end_line=end_line)
        if mark is not None:
            self._goto_mark = mark
            self._invalidate_body_paint()
            self._scroll_to_line_mark(mark)
            call_after_refresh = getattr(self, "call_after_refresh", None)
            if callable(call_after_refresh):
                landed_document = document

                def scroll_after_layout() -> None:
                    if self.document is landed_document and self._goto_mark == mark:
                        self._scroll_to_line_mark(mark)
                        self._after_scroll()

                call_after_refresh(scroll_after_layout)
        self._forward_trail.clear()
        self._update_trail()
        self._update_footer()
        self._update_subject()
        self._start_syntax_preparation_after_paint()
        # History attaches to every section no matter how it was opened:
        # start discovery after navigating (in place or via ctrl+w).
        try:
            start_history = getattr(self, "_start_history_discovery_after_paint", None)
            if callable(start_history):
                start_history()
        except Exception:
            pass

    def _link_context_for_section_index(
        self: Any,
        section_index: int,
    ) -> LinkResolutionContext | None:
        if not 0 <= section_index < len(self.document.sections):
            return self.document.link_context
        section = self.document.sections[section_index]
        return merge_link_context(
            section.link_anchors,
            self.document.link_context,
            owner=section.owner,
        )

    def _origin_for_section_index(self: Any, section_index: int) -> PagerOrigin:
        if not 0 <= section_index < len(self.document.sections):
            return self.document.origin
        return section_origin(
            self.document.sections[section_index], self.document.origin
        )

    def _is_target_dangling(
        self: Any,
        section_index: int,
        target: PagerTargetSpan,
    ) -> bool:
        origin = self._origin_for_section_index(section_index)
        identity = target_resolution_cache_identity(target, origin)
        if identity is None:
            return False
        return (
            self._dangling_ref_key(
                identity,
                self._link_context_for_section_index(section_index),
            )
            in self._dangling_refs
        )

    def _dangling_ref_key(
        self: Any,
        ref: object,
        context: LinkResolutionContext | None,
    ) -> DanglingRefKey:
        del self
        if context is None:
            return ref, (), owner_cache_key(None)
        return (
            ref,
            tuple(
                (anchor.directory, anchor.workspace_num) for anchor in context.anchors
            ),
            owner_cache_key(context.owner),
        )


def _as_link_resolution(result: LinkResolution | LinkTarget | None) -> LinkResolution:
    if isinstance(result, LinkResolution):
        return result
    if isinstance(result, LinkTarget):
        return LinkResolution(target=result)
    return LinkResolution()
