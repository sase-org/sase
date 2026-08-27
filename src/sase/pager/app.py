"""``SasePager``: the standalone Textual reading surface.

Not wired to any caller yet (design doc phase `viewer`). ``sase bead show``,
the Agents-tab ``v`` keymap, and the future ``sase pager`` command all run
this same app in-process — the CLI calls ``.run()``, ACE runs it inside
``with self.suspend():`` — the way ``MemoryReviewTuiApp`` already proves both
halves of this exact pattern in this tree (design doc section D1).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass
from typing import Literal

from rich.rule import Rule
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.events import Key, Resize
from textual.widgets import Static

from sase.ace.tui.actions.clipboard._delivery import schedule_copy_delivery
from sase.ace.tui.actions.navigation.jump_hints import (
    JumpHintMatchOutcome,
    match_jump_hint,
    normalize_jump_key,
)
from sase.ace.tui.graphics import view_artifact_files
from sase.ace.tui.modals.trail_strip import TrailStripEntry, build_trail_strip
from sase.ace.tui.util.external_tool import suspend_for_external_tool
from sase.ace.tui.util.pump_tasks import cancel_pump_free_tasks, spawn_pump_free_task
from sase.ace.tui.util.trace import tui_trace
from sase.ace.tui.widgets._prompt_jump_target import build_jump_editor_argv
from sase.ace.tui.widgets.vim_search_controller import (
    SearchViewport,
    VimSearchController,
    VimSearchMode,
)
from sase.pager._chrome import footer_legend, section_accent, subject_line
from sase.pager._help import PagerHelpScreen
from sase.pager._labels import (
    LabelWindowScope,
    PAGER_LABEL_TWO_KEY_CAPACITY,
    PagerLabel,
    PagerLabelLayer,
    build_label_layer,
    row_for_character_offset,
)
from sase.pager._layout import (
    ComposedBody,
    compose_body,
    current_section_index,
    search_corpus,
)
from sase.pager._styles import PAGER_CSS
from sase.pager.document import (
    PagerDocument,
    PagerSection,
    PagerTargetSpan,
    target_resolution_ref,
)
from sase.pager.link_scan import LinkSpanKind
from sase.pager.resolve import (
    LinkTarget,
    LinkTargetKind,
    copy_text_for_target,
    resolve_ref,
)
from sase.pager.trail import PagerSearchState, PagerTrailEntry, append_bounded_trail

PendingAction = Literal["follow", "copy", "edit"]

#: The key that arms each non-follow pending action, so a second press of
#: that same key can be recognized as the doubled ``yy``/``EE`` form (design
#: doc section D8) instead of an invalid label key.
_PENDING_ACTION_KEYS: dict[PendingAction, str] = {"copy": "y", "edit": "E"}


@dataclass(frozen=True, slots=True)
class PagerExit:
    """The result of a finished ``SasePager`` run.

    ``trail_exhausted`` lets a host resume its own history when a pager-owned
    trail has already been fully walked back.
    """

    trail_exhausted: bool = False


class _PagerBodyScroll(VerticalScroll):
    """The body scroll container; its own width drives layout caching."""

    def on_resize(self, _event: Resize) -> None:
        app = self.app
        if isinstance(app, SasePager):
            app._ensure_body()
            app._update_subject()


class SasePager(App[PagerExit]):
    """A link-traversing document reader: chrome, scrollable body, footer.

    This phase paints no jump-hint keys yet (that is the ``labels`` phase) —
    it only owns the sticky chrome, the virtualized scrollable body, section
    rules, ``ctrl+n``/``ctrl+p`` scroll-to-header, the availability-driven
    footer, and a re-hosted vim search.
    """

    ENABLE_COMMAND_PALETTE = False
    CSS = PAGER_CSS

    BINDINGS = [
        Binding("q,escape", "close_pager", "Close"),
        Binding("j,down", "scroll_down", "Down"),
        Binding("k,up", "scroll_up", "Up"),
        Binding("ctrl+d", "scroll_half_down", "Half Down"),
        Binding("ctrl+u", "scroll_half_up", "Half Up"),
        Binding("g", "scroll_top", "Top"),
        Binding("G", "scroll_bottom", "Bottom"),
        Binding("ctrl+n", "next_section", "Next Section"),
        Binding("ctrl+p", "prev_section", "Prev Section"),
        Binding("backspace,ctrl+o", "trail_back", "Back"),
        Binding("ctrl+i", "trail_forward", "Forward"),
        Binding("r", "refresh", "Refresh"),
        Binding("y", "arm_copy", "Copy"),
        Binding("E", "arm_edit", "Edit"),
        Binding("question_mark", "show_help", "Keys"),
    ]

    def __init__(self, document: PagerDocument) -> None:
        super().__init__()
        self.document = document
        self._body: ComposedBody | None = None
        self._body_width: int | None = None
        self._label_layer: PagerLabelLayer | None = None
        self._label_pending_prefix = ""
        self._label_window_scope: LabelWindowScope | None = None
        self._last_activated_label: PagerLabel | None = None
        self._pending_action: PendingAction = "follow"
        self._dangling_refs: set[str] = set()
        self._resolve_generation = 0
        self._search = VimSearchController(self)
        self._back_trail: list[PagerTrailEntry] = []
        self._forward_trail: list[PagerTrailEntry] = []
        self._footer_status: str | None = None

    def on_unmount(self) -> None:
        cancel_pump_free_tasks(self)

    def compose(self) -> ComposeResult:
        with Vertical(id="pager-root"):
            yield Static(id="pager-subject")
            yield Static(id="pager-trail", classes="hidden")
            yield Static(id="pager-chrome-rule")
            with _PagerBodyScroll(id="pager-body-scroll"):
                yield Static(id="pager-body")
            yield Static(id="pager-search-command", classes="hidden")
            yield Static(id="pager-footer-rule")
            yield Static(id="pager-footer")

    def on_mount(self) -> None:
        with tui_trace("pager.open", sections=len(self.document.sections)):
            self.query_one("#pager-chrome-rule", Static).update(Rule(style="dim"))
            self.query_one("#pager-footer-rule", Static).update(Rule(style="dim"))
            self._ensure_body()
            self._update_trail()
            self._update_footer()
            self._update_subject()

    def on_key(self, event: Key) -> None:
        """Give the re-hosted vim search first refusal on every keypress.

        ``allow_question_mark_reverse=False`` reserves ``?`` for the wider
        help binding once committed search exits, per the controller's own
        documented escape hatch for hosts with a house ``?`` binding.
        ``passthrough_exit_keys=None`` exits committed search on any other
        key rather than Zoom's narrower structural set, because this app has
        only one scroll target — there is no second panel for a raw ``j``
        to land on while search is still showing.

        Skipped entirely while a modal (such as the help screen) is on top,
        so a search cannot silently start underneath it.
        """
        if len(self.screen_stack) > 1:
            return
        disposition = self._search.handle_key(
            event.key,
            event.character,
            passthrough_exit_keys=None,
            allow_question_mark_reverse=False,
        )
        if disposition == "consumed":
            event.prevent_default()
            event.stop()
            return

        if self._handle_label_key(event):
            event.prevent_default()
            event.stop()

    def action_close_pager(self) -> None:
        self.exit(PagerExit())

    def action_scroll_down(self) -> None:
        self._body_scroll().scroll_relative(y=1, animate=False)
        self._after_scroll()

    def action_scroll_up(self) -> None:
        self._body_scroll().scroll_relative(y=-1, animate=False)
        self._after_scroll()

    def action_scroll_half_down(self) -> None:
        scroll = self._body_scroll()
        scroll.scroll_relative(y=max(1, scroll.size.height // 2), animate=False)
        self._after_scroll()

    def action_scroll_half_up(self) -> None:
        scroll = self._body_scroll()
        scroll.scroll_relative(y=-max(1, scroll.size.height // 2), animate=False)
        self._after_scroll()

    def action_scroll_top(self) -> None:
        self._body_scroll().scroll_to(y=0, animate=False, immediate=True)
        self._after_scroll()

    def action_scroll_bottom(self) -> None:
        scroll = self._body_scroll()
        scroll.scroll_to(y=scroll.max_scroll_y, animate=False, immediate=True)
        self._after_scroll()

    def action_next_section(self) -> None:
        """Scroll so the next section's rule sits at row 0 (design doc D5).

        This is a scroll, not a screen swap — deliberately unlike
        ``ZoomPanelModal``'s ``ctrl+n``, because the pager is one continuous
        document rather than independently-loaded panels.
        """
        self._goto_section(1)

    def action_prev_section(self) -> None:
        self._goto_section(-1)

    def action_refresh(self) -> None:
        self._body_width = None
        self._ensure_body()
        self._after_scroll()

    def action_show_help(self) -> None:
        self.push_screen(
            PagerHelpScreen(
                section_total=len(self.document.sections),
                label_count=self._visible_label_count(),
                trail_entries=self._trail_strip_entries(),
            )
        )

    def action_trail_back(self) -> None:
        if not self._back_trail:
            self.exit(PagerExit(trail_exhausted=True))
            return
        self._resolve_generation += 1
        target = self._back_trail.pop()
        append_bounded_trail(self._forward_trail, self._current_view_state())
        self._restore_view_state(target)

    def action_trail_forward(self) -> None:
        if not self._forward_trail:
            return
        self._resolve_generation += 1
        target = self._forward_trail.pop()
        append_bounded_trail(self._back_trail, self._current_view_state())
        self._restore_view_state(target)

    def _goto_section(self, direction: int) -> None:
        if self._body is None or len(self.document.sections) <= 1:
            return
        scroll = self._body_scroll()
        offsets = self._body.section_offsets
        index = current_section_index(offsets, int(scroll.scroll_y))
        target = index + direction
        if target >= len(offsets):
            scroll.scroll_to(y=scroll.max_scroll_y, animate=False, immediate=True)
        else:
            target_row = offsets[max(target, 0)]
            scroll.scroll_to(y=target_row, animate=False, immediate=True)
        self._after_scroll()

    def _after_scroll(self) -> None:
        self._refresh_window_scoped_labels_if_needed()
        self.call_after_refresh(self._update_chrome_position)

    def _update_chrome_position(self) -> None:
        self._update_subject()
        self._update_trail()

    def _body_scroll(self) -> _PagerBodyScroll:
        return self.query_one("#pager-body-scroll", _PagerBodyScroll)

    def _ensure_body(self) -> None:
        """Rebuild the composed body only when the body's width changed.

        Sections are frozen and already parsed once at document-construction
        time (``PagerSection.__post_init__``); this only recomputes the
        width-dependent layout — section row offsets and transition rules —
        per ``tui_perf`` rule 8.
        """
        scroll = self._body_scroll()
        width = max(scroll.size.width, 1)
        if self._body is not None and width == self._body_width:
            return
        self._body_width = width
        self._label_layer = self._build_label_layer(width)
        body = compose_body(
            self.document,
            width,
            label_layer=self._label_layer,
            pending_prefix=self._label_pending_prefix,
        )
        self._body = body
        self.query_one("#pager-body", Static).update(body.renderable)

    def _build_label_layer(self, width: int) -> PagerLabelLayer:
        section_offsets = self._body.section_offsets if self._body is not None else ()
        layer = build_label_layer(
            self.document,
            width=width,
            section_offsets=section_offsets,
            dangling_refs=self._dangling_refs,
        )
        if layer.target_count <= PAGER_LABEL_TWO_KEY_CAPACITY:
            self._label_window_scope = None
            return layer

        scope = self._current_label_window_scope()
        return build_label_layer(
            self.document,
            width=width,
            window_scope=scope,
            section_offsets=section_offsets,
            dangling_refs=self._dangling_refs,
        )

    def _current_label_window_scope(self) -> LabelWindowScope:
        scroll = self._body_scroll()
        viewport_height = max(int(scroll.size.height), 1)
        scroll_y = max(int(scroll.scroll_y), 0)
        scope = self._label_window_scope
        if (
            scope is not None
            and scope.start_row <= scroll_y
            and scroll_y + viewport_height <= scope.end_row
        ):
            return scope
        start = max(scroll_y - viewport_height, 0)
        end = scroll_y + viewport_height * 2
        scope = LabelWindowScope(start, max(end, start + 1))
        self._label_window_scope = scope
        return scope

    def _refresh_window_scoped_labels_if_needed(self) -> None:
        layer = self._label_layer
        if layer is None or layer.mode != "window":
            return
        current_scope = self._label_window_scope
        if current_scope is self._current_label_window_scope():
            return
        self._body_width = None
        self._ensure_body()
        self._update_footer()

    def _handle_label_key(self, event: Key) -> bool:
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
            # A second `y`/`E` press is the doubled form (D8) — fall through
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

    def action_arm_copy(self) -> None:
        self._arm_pending_action("copy")

    def action_arm_edit(self) -> None:
        self._arm_pending_action("edit")

    def _arm_pending_action(self, action: Literal["copy", "edit"]) -> None:
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

    def _dispatch_section_action(self, action: Literal["copy", "edit"]) -> None:
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

    def _activate_label(self, label: PagerLabel) -> None:
        self._last_activated_label = label
        action = self._pending_action
        self._pending_action = "follow"
        target = label.target

        if target.kind == LinkSpanKind.URL.value or action == "copy":
            self._copy_target(target)
            return
        if action == "edit":
            self._edit_target(target)
            return
        self._follow_target(target)

    def _repaint_label_state(self) -> None:
        self._body_width = None
        self._ensure_body()
        self._update_footer()

    # -- Press dispatch: copy / edit / follow ------------------------------

    def _copy_target(self, target: PagerTargetSpan) -> None:
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

    def _copy_ref(self, ref: str, *, label: str) -> None:
        schedule_copy_delivery(
            self,
            ref,
            copied_label=label,
            task_name="sase-pager-copy",
            on_failure="toast",
        )

    def _edit_target(self, target: PagerTargetSpan) -> None:
        ref = target_resolution_ref(target, self.document.origin)
        if ref is None:
            self.notify("Nothing to edit here.", severity="warning")
            return
        self._resolve_and_dispatch(ref, intent="edit")

    def _follow_target(self, target: PagerTargetSpan) -> None:
        ref = target_resolution_ref(target, self.document.origin)
        if ref is None:
            self.notify("Nothing to follow here.", severity="warning")
            return
        self._resolve_and_dispatch(ref, intent="follow")

    def _resolve_and_dispatch(
        self, ref: str, *, intent: Literal["follow", "edit"]
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
                target = await asyncio.to_thread(resolve_ref, ref)
            except Exception as exc:  # noqa: BLE001 - a press must never crash the pager
                if generation == self._resolve_generation and self.document is document:
                    self._set_footer_status(None)
                    self.notify(f"Could not resolve {ref} — {exc}", severity="error")
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
        self,
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

    def _launch_editor(self, target: LinkTarget) -> None:
        if target.edit_path is None:
            self.notify("Nothing to edit here.", severity="warning")
            return
        editor = os.environ.get("EDITOR") or "nvim"
        argv = build_jump_editor_argv(
            editor, str(target.edit_path), target.edit_line, None
        )
        with suspend_for_external_tool(
            self,
            action="pager_open_editor",
            tool_kind="editor",
            command=argv[0],
            path_count=1,
        ):
            subprocess.run(argv, check=False)

    def _show_media(self, target: LinkTarget) -> None:
        with suspend_for_external_tool(
            self,
            action="pager_view_media",
            tool_kind="viewer",
            path_count=len(target.media_specs),
        ):
            result = view_artifact_files(list(target.media_specs))
        if result.warning is not None:
            self.notify(result.warning, severity="warning")

    def _navigate_to_document(
        self, document: PagerDocument, *, line: int | None
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

    # -- Trail -------------------------------------------------------------

    def _push_trail_entry(self) -> None:
        append_bounded_trail(self._back_trail, self._current_view_state())

    def _restore_view_state(self, state: PagerTrailEntry) -> None:
        self.document = state.document
        self._body = None
        self._body_width = None
        self._label_layer = None
        self._label_pending_prefix = ""
        self._label_window_scope = state.label_anchor
        self._last_activated_label = None
        self._pending_action = "follow"
        self._footer_status = None
        self._ensure_body()
        self._restore_search_state(state.search)
        self._update_trail()
        self._update_footer()
        self._update_subject()
        self.call_after_refresh(
            lambda: self._restore_trail_scroll(
                x=state.scroll_x,
                y=state.scroll_y,
            )
        )

    def _restore_trail_scroll(self, *, x: int, y: int) -> None:
        self._body_scroll().scroll_to(x=x, y=y, animate=False, immediate=True)
        self._update_subject()
        self._update_trail()

    def _current_view_state(self) -> PagerTrailEntry:
        section = self._current_section_or_none()
        scroll = self._body_scroll()
        return PagerTrailEntry(
            document=self.document,
            document_identity=self._document_identity(),
            document_title=self.document.title,
            section_identity=section.identity if section is not None else "",
            section_title=section.title if section is not None else self.document.title,
            section_kind=section.kind if section is not None else "",
            scroll_x=int(scroll.scroll_x),
            scroll_y=int(scroll.scroll_y),
            search=self._current_search_state(),
            label_anchor=self._label_window_scope,
        )

    def _current_search_state(self) -> PagerSearchState:
        return PagerSearchState(
            mode=self._search.mode,
            direction=self._search.direction,
            query=self._search.query,
            corpus=self._search.corpus,
            line_starts=tuple(self._search.line_starts),
            match_spans=tuple(self._search.match_spans),
            current_selection=self._search.current_selection,
            origin_offset=self._search.origin_offset,
            restore_scroll_x=self._search.restore_scroll_x,
            restore_scroll_y=self._search.restore_scroll_y,
            last_search=self._search.last_search,
        )

    def _reset_search_state(self) -> None:
        if self._search.is_active:
            self._search.exit(restore_scroll=False, refresh=False)
        self._search = VimSearchController(self)
        self.vim_search_hide_overlay()

    def _restore_search_state(self, state: PagerSearchState) -> None:
        if self._search.is_active:
            self._search.exit(restore_scroll=False, refresh=False)
        self._search.mode = state.mode
        self._search.direction = state.direction
        self._search.query = state.query
        self._search.corpus = state.corpus
        self._search.line_starts = state.line_starts
        self._search.match_spans = state.match_spans
        self._search.current_selection = state.current_selection
        self._search.origin_offset = state.origin_offset
        self._search.restore_scroll_x = state.restore_scroll_x
        self._search.restore_scroll_y = state.restore_scroll_y
        self._search.last_search = state.last_search
        if state.mode == "off":
            self.vim_search_hide_overlay()
            return
        self.vim_search_show_overlay()
        self._search._render_overlay()
        self._search._render_command_line()
        self.vim_search_focus_overlay()

    def _document_identity(self) -> str:
        if len(self.document.sections) == 1:
            return self.document.sections[0].identity
        if self.document.sections:
            return "|".join(section.identity for section in self.document.sections)
        return self.document.title

    def _current_section_or_none(self) -> PagerSection | None:
        if not self.document.sections:
            return None
        return self._current_section()

    def _trail_strip_entries(self) -> tuple[TrailStripEntry, ...]:
        if not self._back_trail:
            return ()
        entries = [
            TrailStripEntry(entry.section_title, kind=entry.section_kind)
            for entry in self._back_trail
        ]
        current = self._current_section_or_none()
        if current is None:
            entries.append(TrailStripEntry(self.document.title))
        else:
            entries.append(TrailStripEntry(current.title, kind=current.kind))
        return tuple(entries)

    def _update_trail(self) -> None:
        trail = self.query_one("#pager-trail", Static)
        entries = self._trail_strip_entries()
        if not entries:
            trail.update("")
            trail.add_class("hidden")
            return
        width = max(int(trail.size.width) - 2, 1)
        current = self._current_section_or_none()
        accent = "#AFAFAF" if current is None else section_accent(current.kind)
        trail.update(build_trail_strip(entries, accent=accent, max_width=width))
        trail.remove_class("hidden")

    def _set_footer_status(self, status: str | None) -> None:
        self._footer_status = status
        self._update_footer()

    def _row_for_document_line(self, line: int) -> int | None:
        if not self.document.sections:
            return None
        text = self.document.sections[0].plain_text
        lines = text.split("\n")
        if line < 1 or line > len(lines):
            return None
        offset = sum(len(entry) + 1 for entry in lines[: line - 1])
        width = self._body_width or 1
        return row_for_character_offset(text, offset, width)

    def _current_section_index(self) -> int:
        offsets = self._body.section_offsets if self._body is not None else (0,)
        return current_section_index(offsets, int(self._body_scroll().scroll_y))

    def _current_section(self) -> PagerSection:
        return self.document.sections[self._current_section_index()]

    def _visible_label_count(self) -> int:
        if self._label_layer is None:
            return 0
        return self._label_layer.visible_label_count

    def _update_footer(self) -> None:
        self.query_one("#pager-footer", Static).update(
            footer_legend(
                section_total=len(self.document.sections),
                label_count=self._visible_label_count(),
                pending_prefix=self._label_pending_prefix,
                pending_action=self._pending_action,
                trail_back_count=len(self._back_trail),
                trail_forward_count=len(self._forward_trail),
                status=self._footer_status,
            )
        )

    def _update_subject(self) -> None:
        scroll = self._body_scroll()
        total = len(self.document.sections)
        width = max(scroll.size.width, 1)
        subject_widget = self.query_one("#pager-subject", Static)
        if total == 0:
            subject_widget.update(Text(self.document.title, style="bold"))
            return

        offsets = self._body.section_offsets if self._body is not None else (0,)
        index = current_section_index(offsets, int(scroll.scroll_y))
        section = self.document.sections[index]
        percent = (
            100
            if scroll.max_scroll_y <= 0
            else min(100, round(scroll.scroll_y / scroll.max_scroll_y * 100))
        )
        char_count = sum(len(part.plain_text) for part in self.document.sections)
        subject_widget.update(
            subject_line(
                self.document,
                section,
                section_index=index + 1,
                section_total=total,
                scroll_percent=percent,
                char_count=char_count,
                width=width,
            )
        )

    # -- VimSearchController host protocol --------------------------------

    def vim_search_corpus(self) -> str:
        return search_corpus(self.document)

    def vim_search_origin_scroll(self) -> tuple[int, int]:
        scroll = self._body_scroll()
        return (int(scroll.scroll_x), int(scroll.scroll_y))

    def vim_search_overlay_viewport(self) -> SearchViewport:
        scroll = self._body_scroll()
        region = scroll.scrollable_content_region
        return SearchViewport(
            scroll_x=int(scroll.scroll_x),
            scroll_y=int(scroll.scroll_y),
            width=region.width,
            height=region.height,
        )

    def vim_search_started(self) -> None:
        """No live refresh source to pause: the document is immutable."""

    def vim_search_exited(self, *, refresh: bool) -> None:
        """The body is already restored by ``vim_search_hide_overlay``."""

    def vim_search_show_overlay(self) -> None:
        self.query_one("#pager-search-command", Static).remove_class("hidden")

    def vim_search_hide_overlay(self) -> None:
        if self._body is not None:
            self.query_one("#pager-body", Static).update(self._body.renderable)
        command = self.query_one("#pager-search-command", Static)
        command.update("")
        command.add_class("hidden")

    def vim_search_paint_overlay(self, content: Text) -> None:
        self.query_one("#pager-body", Static).update(content)

    def vim_search_command_width(self) -> int:
        command = self.query_one("#pager-search-command", Static)
        return max(0, int(command.size.width) - 2)

    def vim_search_paint_command_line(
        self,
        content: Text,
        mode: VimSearchMode,
    ) -> None:
        command = self.query_one("#pager-search-command", Static)
        command.update(content)
        command.remove_class("hidden")

    def vim_search_scroll_overlay(self, *, x: int, y: int) -> None:
        self._body_scroll().scroll_to(x=x, y=y, animate=False, immediate=True)

    def vim_search_restore_scroll(self, *, x: int, y: int) -> None:
        def restore() -> None:
            self._body_scroll().scroll_to(x=x, y=y, animate=False, immediate=True)
            self._update_subject()

        self.call_after_refresh(restore)

    def vim_search_focus_overlay(self) -> None:
        self.call_after_refresh(self._body_scroll().focus)

    def vim_search_focus_native(self) -> None:
        self.call_after_refresh(self._body_scroll().focus)

    def vim_search_notify(self, message: str) -> None:
        self.notify(message, severity="information")


__all__ = ["PagerExit", "SasePager"]
