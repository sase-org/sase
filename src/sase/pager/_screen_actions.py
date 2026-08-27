"""Label-key handling and copy/edit/follow dispatch for ``PagerScreen``."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Literal

from textual.events import Key

from sase.ace.tui.actions.clipboard._delivery import schedule_copy_delivery
from sase.ace.tui.actions.navigation.jump_hints import (
    JumpHintMatchOutcome,
    match_jump_hint,
    normalize_jump_key,
)
from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.ace.tui.widgets._prompt_jump_target import build_jump_editor_argv
from sase.pager._labels import LabelWindowScope, PagerLabel, PagerLabelLayer
from sase.pager._layout import ComposedBody
from sase.pager.app import PendingAction
from sase.pager.document import PagerDocument, PagerTargetSpan, target_resolution_ref
from sase.pager.link_scan import LinkSpanKind
from sase.pager.resolve import (
    LinkTarget,
    LinkTargetKind,
    copy_text_for_target,
)

#: The key that arms each non-follow pending action, so a second press of
#: that same key can be recognized as the doubled ``yy``/``EE`` form (design
#: doc section D8) instead of an invalid label key.
_PENDING_ACTION_KEYS: dict[PendingAction, str] = {"copy": "y", "edit": "E"}


def _screen_module() -> Any:
    return sys.modules["sase.pager.screen"]


class PagerActionMixin:
    """Handle link labels and resolve selected targets."""

    _body: ComposedBody | None
    _body_width: int | None
    _label_layer: PagerLabelLayer | None
    _label_window_scope: LabelWindowScope | None
    _last_activated_label: PagerLabel | None
    _pending_action: PendingAction

    def _handle_label_key(self: Any, event: Key) -> bool:
        layer = self._label_layer
        hint_to_label_index = layer.hint_to_label_index if layer is not None else {}
        armed = self._pending_action != "follow"
        if not hint_to_label_index and not armed:
            return False

        key = normalize_jump_key(event.key, event.character)
        if (
            armed
            and not self._label_pending_prefix
            and key == _PENDING_ACTION_KEYS[self._pending_action]
        ):
            # A second `y`/`E` press is the doubled form (D8) - fall through
            # to the binding that armed this prefix so it can recognize the
            # double-press itself, rather than swallowing it as invalid here.
            return False

        match = match_jump_hint(
            hint_to_label_index,
            self._label_pending_prefix,
            key,
        )
        if match.outcome is JumpHintMatchOutcome.PENDING:
            self._label_pending_prefix = match.prefix
            self._repaint_label_state()
            return True
        if match.outcome is JumpHintMatchOutcome.COMPLETE:
            label_index = match.target
            if label_index is None or layer is None:
                return False
            self._label_pending_prefix = ""
            self._activate_label(layer.labels[label_index])
            self._repaint_label_state()
            return True
        if self._label_pending_prefix or armed:
            self._label_pending_prefix = ""
            self._pending_action = "follow"
            self._repaint_label_state()
            self.notify("No link label matches that key.", severity="information")
            return True
        return False

    def action_arm_copy(self: Any) -> None:
        self._arm_pending_action("copy")

    def action_arm_edit(self: Any) -> None:
        self._arm_pending_action("edit")

    def _arm_pending_action(self: Any, action: Literal["copy", "edit"]) -> None:
        if self._pending_action == action:
            # Doubled (``yy``/``EE``): act on the current section itself,
            # per design doc section D8, rather than waiting on a label.
            self._pending_action = "follow"
            self._label_pending_prefix = ""
            self._dispatch_section_action(action)
            self._repaint_label_state()
            return
        self._pending_action = action
        self._label_pending_prefix = ""
        self._repaint_label_state()

    def _dispatch_section_action(self: Any, action: Literal["copy", "edit"]) -> None:
        if not self.document.sections:
            self.notify("This document has no section to act on.", severity="warning")
            return
        section = self._current_section()
        ref = section.subject_ref
        if ref is None:
            what = "copy" if action == "copy" else "edit"
            self.notify(f"This section has nothing to {what}.", severity="warning")
            return
        if action == "copy":
            self._copy_ref(ref, label="this section")
        else:
            self._resolve_and_dispatch(ref, intent="edit")

    def _activate_label(self: Any, label: PagerLabel) -> None:
        self._last_activated_label = label
        action = self._pending_action
        self._pending_action = "follow"
        target = label.target

        handler = self._attached_handlers.get(target.kind)
        if handler is not None:
            handler(target, action)
            return

        if target.kind == LinkSpanKind.URL.value or action == "copy":
            self._copy_target(target)
            return
        if action == "edit":
            self._edit_target(target)
            return
        self._follow_target(target)

    def _repaint_label_state(self: Any) -> None:
        self._body_width = None
        self._ensure_body()
        self._update_footer()

    def _copy_target(self: Any, target: PagerTargetSpan) -> None:
        if target.kind == LinkSpanKind.URL.value:
            self._copy_ref(target.text, label="link")
            return
        ref = target_resolution_ref(target, self.document.origin)
        if ref is None:
            self.notify("Nothing to copy here.", severity="warning")
            return
        kind = target.kind
        schedule_copy_delivery(
            self,
            lambda: copy_text_for_target(ref, kind),
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

    def _edit_target(self: Any, target: PagerTargetSpan) -> None:
        ref = target_resolution_ref(target, self.document.origin)
        if ref is None:
            self.notify("Nothing to edit here.", severity="warning")
            return
        self._resolve_and_dispatch(ref, intent="edit")

    def _follow_target(self: Any, target: PagerTargetSpan) -> None:
        ref = target_resolution_ref(target, self.document.origin)
        if ref is None:
            self.notify("Nothing to follow here.", severity="warning")
            return
        self._resolve_and_dispatch(ref, intent="follow")

    def _resolve_and_dispatch(
        self: Any, ref: str, *, intent: Literal["follow", "edit"]
    ) -> None:
        if ref in self._dangling_refs:
            self.notify(f"{ref} could not be resolved.", severity="warning")
            return
        self._set_footer_status("loading")
        self._resolve_generation += 1
        generation = self._resolve_generation
        document = self.document

        async def resolve_task() -> None:
            try:
                target = await asyncio.to_thread(self._resolve_ref, ref)
            except Exception as exc:  # noqa: BLE001 - a press must never crash the pager
                if generation == self._resolve_generation and self.document is document:
                    self._set_footer_status(None)
                    self.notify(f"Could not resolve {ref} - {exc}", severity="error")
                return
            if generation != self._resolve_generation or self.document is not document:
                return
            self._apply_resolution(ref, target, intent=intent)

        spawn_pump_free_task(
            self,
            resolve_task(),
            name="sase-pager-resolve",
            registry_attr="_pump_free_resolve_tasks",
        )

    def _apply_resolution(
        self: Any,
        ref: str,
        target: LinkTarget | None,
        *,
        intent: Literal["follow", "edit"],
    ) -> None:
        self._set_footer_status(None)
        if target is None:
            self._dangling_refs.add(ref)
            self.notify(f"{ref} could not be resolved.", severity="warning")
            self._repaint_label_state()
            return
        if intent == "edit":
            self._launch_editor(target)
            return
        if target.kind is LinkTargetKind.MEDIA:
            self._show_media(target)
            return
        if target.document is not None:
            self._push_trail_entry()
            self._navigate_to_document(target.document, line=target.scroll_line)

    def _launch_editor(self: Any, target: LinkTarget) -> None:
        if target.edit_path is None:
            self.notify("Nothing to edit here.", severity="warning")
            return
        editor = os.environ.get("EDITOR") or "nvim"
        argv = build_jump_editor_argv(
            editor, str(target.edit_path), target.edit_line, None
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

    def _navigate_to_document(
        self: Any, document: PagerDocument, *, line: int | None
    ) -> None:
        self.document = document
        self._body = None
        self._body_width = None
        self._label_layer = None
        self._label_pending_prefix = ""
        self._label_window_scope = None
        self._last_activated_label = None
        self._pending_action = "follow"
        self._reset_search_state()
        self._ensure_body()
        scroll = self._body_scroll()
        scroll.scroll_to(x=0, y=0, animate=False, immediate=True)
        row = self._row_for_document_line(line) if line is not None else None
        if row is not None:
            scroll.scroll_to(y=row, animate=False, immediate=True)
        self._forward_trail.clear()
        self._update_trail()
        self._update_footer()
        self._update_subject()


__all__ = ["PagerActionMixin"]
