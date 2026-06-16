"""Frontmatter Panel integration for ``PromptInputBar`` (Phase 3).

Presentation-only glue between the prompt stack and the structured
:class:`~sase.ace.tui.widgets.frontmatter_panel.FrontmatterPanel`:

- the panel is mounted (hidden) directly above ``#prompt-stack`` and auto-shows
  when the bar opens on a prompt that already carries frontmatter;
- typing a leading ``---`` then a newline at the very start of an empty prompt
  promotes into frontmatter mode (distinct from a ``---`` *after* content, which
  stays a multi-agent segment separator);
- ``,f`` focuses the panel and ``esc`` / ``q`` hands focus back to the body,
  removing the frontmatter entirely when the panel is left empty;
- panel edits are persisted onto the stack's byte-stable ``frontmatter`` string
  via :meth:`PromptStackState.set_frontmatter_model`, so ``parse_multi_prompt``
  stays the launch source of truth.

The model / validation logic lives in the panel and the Phase 1/2 cores; this
mixin only wires the panel into the bar's lifecycle, focus, and height.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.dom import DOMNode

from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_stack import PromptStackState
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    xprompt_assist_entry_from_local_xprompt,
)
from sase.xprompt.prompt_frontmatter import PromptFrontmatter

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object

# The exact body a fresh ``---`` + newline produces at the very start of an empty
# single-pane prompt: the trigger for promoting into frontmatter mode.
_FRONTMATTER_TRIGGER_BODY = "---\n"


class PromptInputBarFrontmatterMixin(_MixinBase):
    """Mount, trigger, focus, persist, and size the Frontmatter Panel."""

    if TYPE_CHECKING:
        _mode: str
        _stack: PromptStackState

        def active_text_area(self) -> PromptTextArea: ...
        def _refresh_title(self, mode_suffix: str = "") -> None: ...
        def _schedule_height_update(self) -> None: ...
        def _sync_state_from_widgets(self) -> None: ...

    # Cache of (frontmatter string -> assist entries) so completion in every
    # pane reads the panel's *live* local xprompts without reparsing the YAML on
    # each keystroke.  Keyed by the exact frontmatter string the stack carries,
    # so a one-entry cache invalidates itself the moment the user edits a helper.
    _local_xprompt_cache: tuple[str, list[XPromptAssistEntry]] | None = None

    # -- local xprompt completion parity --------------------------------------

    def local_xprompt_assist_entries(self) -> list[XPromptAssistEntry]:
        """Assist entries for the local xprompts declared in the live frontmatter.

        Parses the stack's current ``frontmatter`` string into the structured
        model and converts each ``xprompts:`` helper into an
        :class:`XPromptAssistEntry`, so panes can merge them into ``<ctrl+t>`` /
        ``<ctrl+l>`` completion and the argument-hint resolver.  Returns ``[]``
        when there is no frontmatter or it declares no local xprompts.
        """
        frontmatter = self._stack.frontmatter
        if not frontmatter:
            return []
        cached = self._local_xprompt_cache
        if cached is not None and cached[0] == frontmatter:
            return cached[1]
        try:
            model = PromptFrontmatter.parse(frontmatter)
        except Exception:
            # A mid-edit / invalid block (e.g. a non-underscore name) simply
            # contributes no completions rather than breaking the pane.
            entries: list[XPromptAssistEntry] = []
        else:
            entries = [
                xprompt_assist_entry_from_local_xprompt(name, xprompt)
                for name, xprompt in model.xprompts.items()
            ]
        self._local_xprompt_cache = (frontmatter, entries)
        return entries

    # -- lookup ---------------------------------------------------------------

    def _frontmatter_panel(self) -> FrontmatterPanel | None:
        """Return the mounted panel, or ``None`` (feedback / approve bars)."""
        try:
            return self.query_one("#frontmatter-panel", FrontmatterPanel)
        except Exception:
            return None

    def _frontmatter_panel_visible(self) -> bool:
        """True when the panel is mounted and not hidden."""
        panel = self._frontmatter_panel()
        return panel is not None and not panel.has_class("hidden")

    def _frontmatter_panel_reserved_rows(self) -> int:
        """Rows the visible panel needs, for the bar's height calculation."""
        panel = self._frontmatter_panel()
        if panel is None or panel.has_class("hidden"):
            return 0
        return panel.reserved_height

    def _frontmatter_panel_owns_focus(self) -> bool:
        """True when the panel (or its inline / raw editor) currently has focus.

        Lets a blurred prompt pane skip its "snap focus back" behavior while the
        user is editing frontmatter above it.
        """
        panel = self._frontmatter_panel()
        focused = self.app.focused
        if panel is None or focused is None:
            return False
        node: DOMNode | None = focused
        while node is not None:
            if node is panel:
                return True
            node = node.parent
        return False

    # -- show / hide / focus --------------------------------------------------

    def _show_frontmatter_panel(self, *, focus: bool) -> None:
        """Reveal the panel synced to the stack's current frontmatter.

        Focusing is deferred to after the next refresh: a panel just un-hidden
        (``display: none`` → shown) is not focusable until Textual recomputes
        layout, so focusing in the same frame is silently dropped.
        """
        panel = self._frontmatter_panel()
        if panel is None:
            return
        panel.set_frontmatter(self._stack.frontmatter)
        panel.remove_class("hidden")
        self._refresh_title()
        if focus:
            self.call_after_refresh(panel.focus_panel)
        self._schedule_height_update()

    def focus_frontmatter_panel(self) -> None:
        """Focus the panel (the ``,f`` keymap); show it first if hidden."""
        if self._mode != "prompt":
            return
        panel = self._frontmatter_panel()
        if panel is None:
            return
        self._sync_state_from_widgets()
        if panel.has_class("hidden"):
            self._show_frontmatter_panel(focus=True)
            return
        panel.set_frontmatter(self._stack.frontmatter)
        self.call_after_refresh(panel.focus_panel)
        self._schedule_height_update()

    def auto_show_frontmatter_panel(self) -> None:
        """Auto-show (without stealing focus) when opening on existing frontmatter."""
        if self._mode != "prompt" or not self._stack.frontmatter:
            return
        self._show_frontmatter_panel(focus=False)

    # -- trigger --------------------------------------------------------------

    def _should_reserve_for_frontmatter(self, text_area: PromptTextArea) -> bool:
        """True while a lone leading ``---`` should wait to become frontmatter.

        Reserves a bare ``---`` typed at the very start of an empty single-pane
        prompt for the frontmatter trigger so live-split does not first turn it
        into two empty panes; the panel opens once the newline lands.
        """
        return (
            self._is_fresh_frontmatter_slot()
            and text_area.document.line_count == 1
            and text_area.document.get_line(0).rstrip() == "---"
        )

    def _maybe_open_frontmatter_panel(self, text_area: PromptTextArea) -> bool:
        """Promote to frontmatter mode on a leading ``---`` + newline.

        Returns ``True`` when the panel was opened so the caller skips the live
        split.  Removes the typed ``---\\n`` from the body and focuses the empty
        panel; a later whole-stack submit re-attaches the authored frontmatter.
        """
        if not self._is_fresh_frontmatter_slot():
            return False
        if text_area.text != _FRONTMATTER_TRIGGER_BODY:
            return False
        text_area.load_text("")
        self._sync_state_from_widgets()
        self._show_frontmatter_panel(focus=True)
        return True

    def _is_fresh_frontmatter_slot(self) -> bool:
        """True for an empty single-pane prompt with no frontmatter / panel yet."""
        return (
            self._mode == "prompt"
            and len(self._stack) == 1
            and self._stack.selected_index == 0
            and not self._stack.frontmatter
            and not self._frontmatter_panel_visible()
        )

    # -- panel messages -------------------------------------------------------

    def on_frontmatter_panel_changed(self, event: FrontmatterPanel.Changed) -> None:
        """Persist a panel edit onto the stack's frontmatter string."""
        event.stop()
        self._stack.set_frontmatter_model(event.model)
        self._refresh_title()
        self._schedule_height_update()

    def on_frontmatter_panel_closed(self, event: FrontmatterPanel.Closed) -> None:
        """Return focus to the body; drop frontmatter when left empty."""
        event.stop()
        panel = self._frontmatter_panel()
        if event.is_empty:
            self._stack.frontmatter = ""
            if panel is not None:
                panel.add_class("hidden")
        try:
            text_area = self.active_text_area()
            text_area.focus()
            text_area._enter_insert_mode()
        except Exception:
            pass
        self._refresh_title()
        self._schedule_height_update()

    def on_frontmatter_panel_add_requested(
        self, event: FrontmatterPanel.AddRequested
    ) -> None:
        """Open the add-property picker and route the choice back to the panel."""
        event.stop()
        panel = self._frontmatter_panel()
        if panel is None:
            return
        from sase.ace.tui.modals import AddableProperty, AddPropertyModal

        properties = [
            AddableProperty(name=name, description=description)
            for name, description in panel.addable_properties()
        ]
        if not properties:
            return

        def _on_pick(field: str | None) -> None:
            chosen = self._frontmatter_panel()
            if chosen is None:
                return
            if field:
                chosen.begin_add(field)
            else:
                chosen.focus_panel()

        self.app.push_screen(AddPropertyModal(properties), _on_pick)
