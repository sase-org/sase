"""Frontmatter Panel integration for ``PromptInputBar`` (Phase 3).

Presentation-only glue between the prompt stack and the structured
:class:`~sase.ace.tui.widgets.frontmatter_panel.FrontmatterPanel`:

- the panel is mounted (hidden) directly above ``#prompt-stack`` and auto-shows
  when the bar opens on a prompt that already carries frontmatter;
- the normal-mode ``g=`` keymap toggles the panel from the body and back (the
  panel routes its own in-panel ``g=`` here too) and ``esc`` / ``q`` hands focus
  back to the body, removing the frontmatter entirely when the panel is left
  empty;
- panel edits are persisted onto the stack's byte-stable ``frontmatter`` string
  via :meth:`PromptStackState.set_frontmatter_model`, so ``parse_multi_prompt``
  stays the launch source of truth.

The model / validation logic lives in the panel and the Phase 1/2 cores; this
mixin only wires the panel into the bar's lifecycle, focus, and height.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from textual.dom import DOMNode

from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_stack import PromptStackState
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    xprompt_assist_entry_from_local_xprompt,
)
from sase.xprompt.models import InputArg
from sase.xprompt.prompt_frontmatter import PromptFrontmatter

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.xprompt.models import XPrompt
else:
    _MixinBase = object


@dataclass(slots=True)
class InlineExpansionTransaction:
    """A single ``#@`` + ``Ctrl+I`` inline expansion that auto-staged inputs.

    Couples the prompt-frontmatter inputs an inline expansion staged to the body
    splice that introduced them, so prompt NORMAL-mode ``u`` / ``Ctrl+R`` on the
    originating pane can unstage and restage exactly those auto-staged inputs in
    lockstep with the (already undoable) body edit.

    The body splice stays the source of truth: :attr:`before_text` /
    :attr:`after_text` are the originating pane's full text immediately before
    and after the splice, so a later ``undo()`` / ``redo()`` is recognized purely
    by the text transition it produces -- no reaching into Textual's private
    history stacks. :attr:`inputs` are the (non-step) inputs the expanded body
    depends on; :attr:`active` tracks whether the body edit is currently applied.
    """

    text_area: PromptTextArea
    before_text: str
    after_text: str
    inputs: list[InputArg] = field(default_factory=list)
    active: bool = True

    @property
    def depends(self) -> set[str]:
        """Names of the inputs the expanded body references."""
        return {arg.name for arg in self.inputs}


@dataclass(frozen=True, slots=True)
class _FrontmatterScope:
    """The active frontmatter storage scope for a prompt pane."""

    key: str
    raw: str
    label: str | None
    has_target: bool


class PromptInputBarFrontmatterMixin(_MixinBase):
    """Mount, focus, persist, and size the Frontmatter Panel."""

    if TYPE_CHECKING:
        _mode: str
        _stack: PromptStackState
        _frontmatter_return_index: int
        _inline_expansion_txns: list[InlineExpansionTransaction]
        _auto_staged_inputs: dict[str, InputArg]

        def active_text_area(self) -> PromptTextArea: ...
        def _apply_active_classes(self) -> None: ...
        def _clear_active_completion_state(self) -> None: ...
        def _refresh_title(self, mode_suffix: str = "") -> None: ...
        def _schedule_height_update(self) -> None: ...
        def _sync_state_from_widgets(self) -> None: ...
        def expand_xprompt_at_target(
            self,
            target_text_area: object,
            pane_id: str,
            trigger_range: tuple[tuple[int, int], tuple[int, int]] | None,
            expanded_text: str,
        ) -> bool: ...
        def _resolve_pane_target(
            self, target_text_area: object, pane_id: str
        ) -> PromptTextArea | None: ...

    # Cache of (scope key, frontmatter string -> assist entries) so completion
    # reads the active scope's live local xprompts without reparsing YAML on each
    # keystroke.  Mini panes have their own scope; agent panes share the stack.
    _local_xprompt_cache: tuple[str, str, list[XPromptAssistEntry]] | None = None

    # -- scope ---------------------------------------------------------------

    def _frontmatter_scope(self, text_area: object | None = None) -> _FrontmatterScope:
        """Return the frontmatter scope for *text_area* or the selected pane."""
        item = self._stack.selected_item
        if text_area is not None:
            text_area_id = getattr(text_area, "id", None)
            if isinstance(text_area_id, str) and text_area_id:
                for candidate in self._stack.items:
                    try:
                        candidate_id = self._pane_id(candidate)  # type: ignore[attr-defined]
                    except Exception:
                        continue
                    if candidate_id == text_area_id:
                        item = candidate
                        break
        target = item.mini_xprompt_target
        if target is not None:
            return _FrontmatterScope(
                key=f"mini:{item.item_id}:{target.name}",
                raw=target.frontmatter,
                label=f"#{target.name}",
                has_target=True,
            )
        return _FrontmatterScope(
            key="stack",
            raw=self._stack.frontmatter,
            label=None,
            has_target=self._stack.binding is not None
            or (getattr(self, "_readonly_xprompt_target", None) is not None),
        )

    def _set_frontmatter_scope_model(
        self,
        model: PromptFrontmatter,
        text_area: object | None = None,
    ) -> None:
        """Persist *model* to the target scope."""
        raw = model.serialize()
        item = self._stack.selected_item
        if text_area is not None:
            text_area_id = getattr(text_area, "id", None)
            if isinstance(text_area_id, str) and text_area_id:
                for candidate in self._stack.items:
                    try:
                        if self._pane_id(candidate) == text_area_id:  # type: ignore[attr-defined]
                            item = candidate
                            break
                    except Exception:
                        continue
        target = item.mini_xprompt_target
        if target is not None:
            item.mini_xprompt_target = replace(target, frontmatter=raw)
        else:
            self._stack.set_frontmatter_model(model)

    # -- local xprompt completion parity --------------------------------------

    def local_xprompt_assist_entries(
        self, text_area: object | None = None
    ) -> list[XPromptAssistEntry]:
        """Assist entries for the local xprompts declared in the live frontmatter.

        Parses the stack's current ``frontmatter`` string into the structured
        model and converts each ``xprompts:`` helper into an
        :class:`XPromptAssistEntry`, so panes can merge them into ``<ctrl+t>`` /
        ``<ctrl+l>`` completion and the argument-hint resolver.  Returns ``[]``
        when there is no frontmatter or it declares no local xprompts.
        """
        scope = self._frontmatter_scope(text_area)
        frontmatter = scope.raw
        if not frontmatter:
            return []
        cached = self._local_xprompt_cache
        if cached is not None and cached[0] == scope.key and cached[1] == frontmatter:
            return cached[2]
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
        self._local_xprompt_cache = (scope.key, frontmatter, entries)
        return entries

    def local_xprompts(self, text_area: object | None = None) -> dict[str, XPrompt]:
        """Local xprompts from the live frontmatter, as real ``XPrompt`` objects.

        Parses the stack's current ``frontmatter`` string with
        :meth:`PromptFrontmatter.parse` and returns its ``xprompts:`` helpers
        keyed by ``_``-prefixed name.  Unlike
        :meth:`local_xprompt_assist_entries` (display-only completion entries),
        this yields the underlying :class:`~sase.xprompt.models.XPrompt`
        objects so the ``#@`` selector can both project them into the catalog
        (via ``xprompt_to_workflow``) and hand them to the ``Ctrl+I``
        inline-expansion helper for recursive resolution.

        Returns ``{}`` when there is no frontmatter or it declares no local
        xprompts; an invalid / mid-edit block (e.g. a non-underscore name)
        contributes nothing rather than raising, so the selector simply omits
        local entries it cannot parse.
        """
        frontmatter = self._frontmatter_scope(text_area).raw
        if not frontmatter:
            return {}
        try:
            model = PromptFrontmatter.parse(frontmatter)
        except Exception:
            return {}
        return dict(model.xprompts)

    def frontmatter_model_for_text_area(
        self, text_area: object | None = None
    ) -> PromptFrontmatter:
        """Return the parsed frontmatter model for a pane's active scope."""
        return PromptFrontmatter.parse(self._frontmatter_scope(text_area).raw)

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

    def _frontmatter_panel_reserved_rows(self, height_cap: int | None = None) -> int:
        """Rows the visible panel needs, for the bar's height calculation."""
        panel = self._frontmatter_panel()
        if panel is None:
            return 0
        if height_cap is not None:
            panel.set_height_cap(height_cap)
        if panel.has_class("hidden"):
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
        scope = self._frontmatter_scope()
        setter = getattr(panel, "set_scope_label", None)
        if callable(setter):
            setter(scope.label)
        panel.set_frontmatter(scope.raw)
        panel.remove_class("hidden")
        self._refresh_title()
        if focus:
            self._frontmatter_return_index = self._stack.selected_index
            self.call_after_refresh(panel.focus_panel)
        self._schedule_height_update()

    def focus_frontmatter_panel(self) -> None:
        """Focus the panel (the ``g=`` show/focus path); show it first if hidden."""
        if self._mode != "prompt":
            return
        panel = self._frontmatter_panel()
        if panel is None:
            return
        self._sync_state_from_widgets()
        if panel.has_class("hidden"):
            self._show_frontmatter_panel(focus=True)
            return
        scope = self._frontmatter_scope()
        setter = getattr(panel, "set_scope_label", None)
        if callable(setter):
            setter(scope.label)
        panel.set_frontmatter(scope.raw)
        self._frontmatter_return_index = self._stack.selected_index
        self.call_after_refresh(panel.focus_panel)
        self._schedule_height_update()

    def toggle_frontmatter_panel(self) -> None:
        """Toggle the xprompt properties panel (the ``g=`` keymap).

        Prompt mode only, and only when a panel is mounted — feedback /
        approve-prompt bars mount none, so the keymap is a no-op there.  Transient
        completion / soft-completion / arg-hint state is cleared first, just as
        the old ``Ctrl+Shift+=`` chord handler did before this structural action.
        When the panel (or its inline / raw editor) already owns focus, hand off
        to the panel so it deactivates with the right per-mode ``esc`` semantics
        and returns focus to the body (the in-panel ``g=`` sequence routes here
        too).  Otherwise reuse the show/focus path so the two entry points stay
        identical: it syncs live pane text, shows the panel if hidden, resyncs it
        from ``self._stack.frontmatter``, focuses it after the refresh, and
        schedules the height update.
        """
        if self._mode != "prompt":
            return
        panel = self._frontmatter_panel()
        if panel is None:
            return
        self._clear_active_completion_state()
        if self._frontmatter_panel_owns_focus():
            panel.deactivate()
            return
        self.focus_frontmatter_panel()

    def auto_show_frontmatter_panel(self) -> None:
        """Auto-show properties for frontmatter or xprompt target editing."""
        if self._mode != "prompt":
            return
        scope = self._frontmatter_scope()
        if not scope.raw and not scope.has_target:
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
        scope = self._frontmatter_scope()
        if scope.raw or scope.has_target:
            self._show_frontmatter_panel(focus=False)
        else:
            panel.add_class("hidden")
            self._schedule_height_update()

    def merge_frontmatter_inputs(
        self,
        inputs: list[InputArg],
        *,
        target_text_area: object | None = None,
    ) -> list[str]:
        """Stage undeclared xprompt inputs in prompt-level frontmatter.

        Existing prompt declarations win on name collisions so inline expansion
        cannot clobber user-authored input types, defaults, or descriptions.

        Returns the names actually added, so the caller can record which
        declarations this expansion now owns: a name skipped on collision is
        *not* owned by this expansion and must survive a later body undo.
        """
        if self._mode != "prompt" or not inputs:
            return []
        try:
            model = PromptFrontmatter.parse(
                self._frontmatter_scope(target_text_area).raw
            )
        except Exception:
            return []

        added: list[str] = []
        for arg in inputs:
            if arg.is_step_input or model.get_input(arg.name) is not None:
                continue
            model.set_input(arg)
            added.append(arg.name)

        if added:
            self._set_frontmatter_scope_model(model, target_text_area)
        self.refresh_frontmatter_panel_from_stack()
        return added

    # -- inline-expansion input transactions ----------------------------------

    def register_inline_expansion(
        self,
        target_text_area: object,
        pane_id: str,
        before_text: str,
        inputs: list[InputArg],
        added: list[str],
    ) -> None:
        """Couple an inline expansion's auto-staged inputs to its body undo.

        Called right after a successful ``Ctrl+I`` body splice + input merge.
        *before_text* is the originating pane's text captured before the splice;
        the live pane's current text is the post-splice ``after_text``. With both
        text snapshots recorded, a later prompt NORMAL-mode ``u`` / ``Ctrl+R`` on
        that pane is matched purely by the text transition it produces and its
        auto-staged inputs are unstaged / restaged in lockstep.

        A stale target (the pane was unmounted/rebuilt while the modal was open),
        a no-op splice, or an expansion with no inputs records nothing.
        """
        text_area = self._resolve_pane_target(target_text_area, pane_id)
        if text_area is None or not inputs:
            return
        after_text = text_area.text
        if before_text == after_text:
            return
        txns = self._inline_expansion_txns
        # Drop transactions whose origin pane is gone so a rebuilt stack never
        # accumulates stale, unmatchable entries.
        txns[:] = [txn for txn in txns if txn.text_area.is_mounted]
        txns.append(
            InlineExpansionTransaction(
                text_area=text_area,
                before_text=before_text,
                after_text=after_text,
                inputs=[arg for arg in inputs if not arg.is_step_input],
            )
        )
        self._snapshot_auto_staged(added, text_area)

    def handle_text_area_undo(
        self, text_area: PromptTextArea, before_text: str, after_text: str
    ) -> None:
        """Unstage auto-staged inputs when a pane undo reverses an expansion.

        *before_text* / *after_text* are the pane's text immediately before and
        after the ``undo()``. When they match a live transaction's after->before
        edit on this pane, that expansion's auto-owned inputs are unstaged
        (subject to shared-input refcounting and user-edit protection). An undo
        that matches no transaction is a no-op here -- the body undo still
        stands.
        """
        for txn in reversed(self._inline_expansion_txns):
            if (
                txn.active
                and txn.text_area is text_area
                and before_text == txn.after_text
                and after_text == txn.before_text
            ):
                self._undo_inline_expansion(txn)
                return

    def handle_text_area_redo(
        self, text_area: PromptTextArea, before_text: str, after_text: str
    ) -> None:
        """Restage auto-staged inputs when a pane redo reapplies an expansion."""
        for txn in reversed(self._inline_expansion_txns):
            if (
                not txn.active
                and txn.text_area is text_area
                and before_text == txn.before_text
                and after_text == txn.after_text
            ):
                self._redo_inline_expansion(txn)
                return

    def _undo_inline_expansion(self, txn: InlineExpansionTransaction) -> None:
        """Mark *txn* undone and unstage the inputs it solely owns."""
        txn.active = False
        try:
            model = PromptFrontmatter.parse(self._frontmatter_scope(txn.text_area).raw)
        except Exception:
            # Mid-edit / invalid frontmatter: leave it untouched rather than
            # clobbering the user's text. The body undo still stands.
            return
        changed = False
        for name in txn.depends:
            owned = self._auto_staged_inputs.get(name)
            if owned is None:
                # Pre-existing / user-authored input, or already unstaged.
                continue
            if self._input_still_needed(name):
                # Another active expansion's body still depends on it.
                continue
            current = model.get_input(name)
            if current is not None and current == owned:
                # Still the auto-staged declaration (user has not edited it).
                if model.remove_input(name):
                    changed = True
            # Whether removed or left in place (user took it over), this
            # expansion no longer owns the name.
            del self._auto_staged_inputs[name]
        if changed:
            self._set_frontmatter_scope_model(model, txn.text_area)
            self.refresh_frontmatter_panel_from_stack()

    def _redo_inline_expansion(self, txn: InlineExpansionTransaction) -> None:
        """Mark *txn* active again and restage the inputs its body needs."""
        txn.active = True
        try:
            model = PromptFrontmatter.parse(self._frontmatter_scope(txn.text_area).raw)
        except Exception:
            return
        restaged: list[str] = []
        for arg in txn.inputs:
            if model.get_input(arg.name) is None:
                model.set_input(arg)
                restaged.append(arg.name)
            # A name already present (user-authored or still staged by another
            # active expansion) is left untouched -- never overwrite it.
        if restaged:
            self._set_frontmatter_scope_model(model, txn.text_area)
            self._snapshot_auto_staged(restaged, txn.text_area)
            self.refresh_frontmatter_panel_from_stack()

    def _input_still_needed(self, name: str) -> bool:
        """True when an active expansion still depends on *name*.

        Called after the transaction being undone has been marked inactive, so a
        ``True`` result means some *other* live expansion's body needs *name* and
        it must not be unstaged yet.
        """
        return any(
            txn.active and name in txn.depends for txn in self._inline_expansion_txns
        )

    def _snapshot_auto_staged(
        self, names: list[str], text_area: object | None = None
    ) -> None:
        """Record the persisted declaration for each freshly auto-staged *name*.

        Snapshots the round-tripped declaration (not the raw expansion arg) so a
        later undo can tell an untouched auto-staged input from one the user has
        since edited in the panel, and only remove the former.
        """
        if not names:
            return
        try:
            model = PromptFrontmatter.parse(self._frontmatter_scope(text_area).raw)
        except Exception:
            return
        for name in names:
            arg = model.get_input(name)
            if arg is not None:
                self._auto_staged_inputs[name] = arg

    # -- panel messages -------------------------------------------------------

    def on_frontmatter_panel_changed(self, event: FrontmatterPanel.Changed) -> None:
        """Persist a panel edit onto the stack's frontmatter string."""
        event.stop()
        self._set_frontmatter_scope_model(event.model)
        self._refresh_title()
        self._schedule_height_update()

    def on_frontmatter_panel_closed(self, event: FrontmatterPanel.Closed) -> None:
        """Return focus to the body; drop frontmatter when left empty."""
        event.stop()
        panel = self._frontmatter_panel()
        if event.is_empty:
            self._set_frontmatter_scope_model(PromptFrontmatter())
            if panel is not None:
                panel.add_class("hidden")

        if event.focus_target == "top":
            target_index = 0
        elif event.focus_target == "bottom":
            target_index = len(self._stack) - 1
        else:
            target_index = (
                self._frontmatter_return_index
                if 0 <= self._frontmatter_return_index < len(self._stack)
                else self._stack.selected_index
            )
        if len(self._stack):
            target_index = max(0, min(target_index, len(self._stack) - 1))
            if target_index != self._stack.selected_index:
                self._stack.focus(target_index)
                self._apply_active_classes()

        self._refresh_title()
        self._schedule_height_update()

        def _focus_target() -> None:
            text_area: PromptTextArea | None
            try:
                text_area = self.active_text_area()
            except Exception:
                text_area = next(iter(self.query(PromptTextArea)), None)
            if text_area is None:
                self.app.screen.set_focus(None)
                return
            text_area.focus()
            text_area._enter_insert_mode()
            text_area.scroll_visible(animate=False)

        self.call_after_refresh(_focus_target)

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
            AddableProperty(
                name=descriptor.name,
                description=descriptor.description,
                kind=descriptor.kind.value,
                example=descriptor.example,
                allowed_values=descriptor.allowed_values,
            )
            for descriptor in panel.addable_properties()
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
