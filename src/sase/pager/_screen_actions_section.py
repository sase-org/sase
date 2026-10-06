"""Section and target actions for ``PagerScreen``.

Owns the doubled ``yy``/``EE`` section dispatch plus the copy/edit/follow
target actions and their editor/media delivery. Label handling lives in
``_screen_actions_labels`` and resolve dispatch in
``_screen_actions_resolve``; this module never imports either sibling.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Literal

from sase.ace.tui.actions.clipboard._delivery import schedule_copy_delivery
from sase.pager.copy_text import copy_text_for_reference, strip_reference_kind
from sase.pager.document import (
    PagerOrigin,
    PagerTargetSpan,
    target_action_destination,
    target_resolution_cache_identity,
)
from sase.pager.link_context import LinkResolutionContext
from sase.pager.link_scan import LinkSpanKind
from sase.pager.resolve import LinkTarget, copy_text_for_target

__all__ = ["PagerActionSectionMixin"]


def _screen_module() -> Any:
    return sys.modules["sase.pager.screen"]


class PagerActionSectionMixin:
    """Dispatch section actions and copy/edit/follow targets."""

    def _dispatch_section_action(self: Any, action: Literal["copy", "edit"]) -> None:
        if not self.document.sections:
            self.notify("This document has no section to act on.", severity="warning")
            return
        section = self._current_section()
        pin = getattr(section, "version_pin", None)
        pinned_ordinal = int(getattr(pin, "ordinal", 0) or 0) if pin is not None else 0
        if action == "copy":
            is_diff, ready, unified = self._diff_unified_for_section(section)
            if is_diff:
                if ready and unified:
                    self._copy_ref(unified, label="unified diff")
                    return
                if ready:
                    self.notify(
                        "No unified diff recorded for this change.",
                        severity="information",
                    )
                else:
                    self.notify(
                        "Diff still loading — try again.", severity="information"
                    )
                return
        if action == "copy" and pinned_ordinal > 0:
            commit = str(getattr(pin, "commit", "") or "")
            live_ref = section.subject_ref or section.identity
            if commit:
                short_path = strip_reference_kind(
                    live_ref, known_kinds=section.known_kinds
                )
                self._copy_ref(f"{commit}:{short_path}", label="this version")
                return
        if action == "edit":
            live_path = self._history_live_path_for_section(section)
            if live_path is not None:
                if live_path == "__deleted__":
                    self.notify(
                        "This version was deleted — no live file to edit.",
                        severity="warning",
                    )
                    return
                index = self._current_section_index()
                owner = section.owner
                context = self._link_context_for_section_index(index)
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
                )
                return
        ref = section.subject_ref
        if ref is None:
            what = "copy" if action == "copy" else "edit"
            self.notify(f"This section has nothing to {what}.", severity="warning")
            return
        if action == "copy":
            index = self._current_section_index()
            context = self._link_context_for_section_index(index)
            known_kinds = section.known_kinds

            def _section_copy_text() -> str:
                return copy_text_for_reference(
                    ref, context=context, known_kinds=known_kinds
                )

            schedule_copy_delivery(
                self,
                _section_copy_text,
                copied_label="this section",
                task_name="sase-pager-copy",
                on_failure="toast",
            )
        else:
            index = self._current_section_index()
            self._resolve_and_dispatch(
                ref,
                intent="edit",
                context=self._link_context_for_section_index(index),
            )

    def _history_live_path_for_section(self: Any, section: Any) -> str | None:
        states = getattr(self, "_history_states", None)
        if not states or section.identity not in states:
            return None
        state = states[section.identity]
        live = getattr(state, "live_section", None)
        if live is not None and getattr(live, "subject_ref", None):
            return str(live.subject_ref)
        pin = getattr(section, "version_pin", None)
        if pin is not None and int(getattr(pin, "ordinal", 0) or 0) > 0:
            # Pinned but no live snapshot: fall back to the subject ref
            # unless the status marks a deletion tombstone.
            if getattr(state, "status", "") == "tombstone":
                return "__deleted__"
            return str(section.subject_ref) if section.subject_ref else None
        return None

    def _copy_target(
        self: Any,
        target: PagerTargetSpan,
        *,
        context: LinkResolutionContext | None,
        origin: PagerOrigin,
    ) -> None:
        destination = target_action_destination(target, origin)
        if destination is None:
            self.notify("Nothing to copy here.", severity="warning")
            return
        if target.kind == LinkSpanKind.URL.value:
            self._copy_ref(destination, label="link")
            return
        kind = target.kind
        schedule_copy_delivery(
            self,
            lambda: copy_text_for_target(destination, kind, context=context),
            copied_label="link",
            task_name="sase-pager-copy",
            on_failure="toast",
        )

    def _copy_ref(self: Any, ref: str, *, label: str) -> None:
        schedule_copy_delivery(
            self,
            ref,
            copied_label=label,
            task_name="sase-pager-copy",
            on_failure="toast",
        )

    def _edit_target(
        self: Any,
        target: PagerTargetSpan,
        *,
        context: LinkResolutionContext | None,
        origin: PagerOrigin,
    ) -> None:
        destination = target_action_destination(target, origin)
        if destination is None:
            self.notify("Nothing to edit here.", severity="warning")
            return
        self._resolve_and_dispatch(
            destination,
            intent="edit",
            context=context,
            cache_identity=target_resolution_cache_identity(target, origin),
        )

    def _follow_target(
        self: Any,
        target: PagerTargetSpan,
        *,
        context: LinkResolutionContext | None,
        origin: PagerOrigin,
        other_pane: bool = False,
    ) -> None:
        destination = target_action_destination(target, origin)
        if destination is None:
            self.notify("Nothing to follow here.", severity="warning")
            return
        self._resolve_and_dispatch(
            destination,
            intent="follow",
            context=context,
            cache_identity=target_resolution_cache_identity(target, origin),
            other_pane=other_pane,
        )

    def _launch_editor(self: Any, target: LinkTarget) -> None:
        if target.edit_path is None:
            self.notify("Nothing to edit here.", severity="warning")
            return
        from sase.ace.tui.widgets._prompt_jump_target import build_jump_editor_argv

        editor = os.environ.get("EDITOR") or "nvim"
        argv = build_jump_editor_argv(
            editor, str(target.edit_path), target.edit_line, target.edit_column
        )
        screen_module = _screen_module()
        with screen_module.suspend_for_external_tool(
            self.app,
            action="pager_open_editor",
            tool_kind="editor",
            command=argv[0],
            path_count=1,
        ):
            screen_module.subprocess.run(argv, check=False)

    def _show_media(self: Any, target: LinkTarget) -> None:
        screen_module = _screen_module()
        with screen_module.suspend_for_external_tool(
            self.app,
            action="pager_view_media",
            tool_kind="viewer",
            path_count=len(target.media_specs),
        ):
            result = screen_module.view_artifact_files(list(target.media_specs))
        if result.warning is not None:
            self.notify(result.warning, severity="warning")
