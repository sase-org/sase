"""Frontmatter Panel integration for ``PromptInputBar`` (Phase 3).

Presentation-only glue between the prompt stack and the structured
:class:`~sase.ace.tui.widgets.frontmatter_panel.FrontmatterPanel`:

- the panel is mounted (hidden) directly above ``#prompt-stack`` and auto-shows
  when the bar opens on a prompt that already carries frontmatter;
- ``,f`` focuses the panel (``Ctrl+Shift+-`` toggles it from the body and back)
  and ``esc`` / ``q`` hands focus back to the body, removing the frontmatter
  entirely when the panel is left empty;
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


class PromptInputBarFrontmatterMixin(_MixinBase):
    """Mount, focus, persist, and size the Frontmatter Panel."""

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

    def toggle_frontmatter_panel(self) -> None:
        """Toggle the xprompt properties panel (the ``Ctrl+Shift+-`` chord).

        Prompt mode only, and only when a panel is mounted — feedback /
        approve-prompt bars mount none, so the chord is a no-op there.  When the
        panel (or its inline / raw editor) already owns focus, hand off to the
        panel so it deactivates with the right per-mode ``esc`` semantics and
        returns focus to the body.  Otherwise reuse the ``,f`` show/focus path so
        the two entry points stay identical: it syncs live pane text, shows the
        panel if hidden, resyncs it from ``self._stack.frontmatter``, focuses it
        after the refresh, and schedules the height update.
        """
        if self._mode != "prompt":
            return
        panel = self._frontmatter_panel()
        if panel is None:
            return
        if self._frontmatter_panel_owns_focus():
            panel.deactivate()
            return
        self.focus_frontmatter_panel()

    def auto_show_frontmatter_panel(self) -> None:
        """Auto-show (without stealing focus) when opening on existing frontmatter."""
        if self._mode != "prompt" or not self._stack.frontmatter:
            return
        self._show_frontmatter_panel(focus=False)

    def refresh_frontmatter_panel_from_stack(self) -> None:
        """Sync the panel's visibility + content to the stack's frontmatter.

        Used after a whole-bar reload (the multi-pane ``^G`` all-editor return): shows and
        re-syncs the panel when the reloaded markdown lifted frontmatter onto the
        stack, and hides it when the edited markdown cleared all properties — so
        the structured panel always reflects the freshly loaded frontmatter
        without stealing focus from the body.
        """
        if self._mode != "prompt":
            return
        panel = self._frontmatter_panel()
        if panel is None:
            return
        if self._stack.frontmatter:
            self._show_frontmatter_panel(focus=False)
        else:
            panel.add_class("hidden")
            self._schedule_height_update()

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
