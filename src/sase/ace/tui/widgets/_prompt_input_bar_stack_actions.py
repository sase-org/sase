"""Stack navigation and structural actions for PromptInputBar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets.prompt_stack import PromptStackState
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object


@dataclass(frozen=True)
class StashedPromptPane:
    """One captured prompt-bar pane handed to the app for persistence.

    The bar captures presentation-side state only (the stripped pane ``text``,
    the bar's shared YAML ``frontmatter``, and the pane's original
    ``pane_index``); the app layer enriches it with id / timestamp / project
    before writing through ``prompt_stash_facade`` (boundary rule D6).
    """

    text: str
    frontmatter: str = ""
    pane_index: int = 0


@dataclass(frozen=True)
class PromptGPrefixHintEntry:
    """One currently available prompt ``g`` prefix hint."""

    key: str
    label: str


@dataclass(frozen=True)
class _PromptGPrefixBinding:
    """Declarative prompt ``g`` prefix binding metadata.

    One table drives both dispatch and the hint panel so the two cannot drift:
    ``action_name`` is the zero-arg method invoked on the second key,
    ``label_method_name`` renders the hint, and ``availability_method_name``
    gates whether the continuation is currently useful (and thus hinted).
    """

    key: str
    action_name: str
    label_method_name: str
    availability_method_name: str


_PROMPT_G_PREFIX_BINDINGS: tuple[_PromptGPrefixBinding, ...] = (
    _PromptGPrefixBinding(
        "enter",
        "submit_active_pane",
        "_g_prefix_label_submit_active",
        "_g_prefix_available_submit_active",
    ),
    _PromptGPrefixBinding(
        "j",
        "_g_focus_next_pane",
        "_g_prefix_label_focus_next",
        "_g_prefix_available_pane_nav",
    ),
    _PromptGPrefixBinding(
        "k",
        "_g_focus_prev_pane",
        "_g_prefix_label_focus_prev",
        "_g_prefix_available_pane_nav",
    ),
    _PromptGPrefixBinding(
        "J",
        "_g_move_pane_down",
        "_g_prefix_label_move_down",
        "_g_prefix_available_pane_nav",
    ),
    _PromptGPrefixBinding(
        "K",
        "_g_move_pane_up",
        "_g_prefix_label_move_up",
        "_g_prefix_available_pane_nav",
    ),
    _PromptGPrefixBinding(
        "-",
        "add_bottom_pane",
        "_g_prefix_label_add_pane",
        "_g_prefix_available_add_pane",
    ),
    _PromptGPrefixBinding(
        "=",
        "toggle_frontmatter_panel",
        "_g_prefix_label_frontmatter",
        "_g_prefix_available_frontmatter",
    ),
    _PromptGPrefixBinding(
        "s",
        "stash_active_pane",
        "_g_prefix_label_stash_active",
        "_g_prefix_available_stash_active",
    ),
    _PromptGPrefixBinding(
        "S",
        "stash_all_panes",
        "_g_prefix_label_stash_all",
        "_g_prefix_available_stash_all",
    ),
    _PromptGPrefixBinding(
        "p",
        "request_load_stash",
        "_g_prefix_label_load_stash",
        "_g_prefix_available_stash_restore",
    ),
    _PromptGPrefixBinding(
        "P",
        "request_restore_stash",
        "_g_prefix_label_restore_stash",
        "_g_prefix_available_stash_restore",
    ),
)


class PromptInputBarStackActionsMixin(_MixinBase):
    """Prompt stack keymaps and completion cleanup."""

    if TYPE_CHECKING:
        Stashed: Any
        RestoreRequested: Any
        _mode: str
        _stack: PromptStackState

        def _apply_active_classes(self) -> None: ...
        def _rebuild_stack(self, enter_mode: str | None = None) -> None: ...
        def _schedule_height_update(self) -> None: ...
        def _sync_state_from_widgets(self) -> None: ...
        def active_text_area(self) -> PromptTextArea: ...
        def toggle_frontmatter_panel(self) -> None: ...
        def hide_file_completions(self) -> None: ...
        def hide_soft_completion(self) -> None: ...

    def dispatch_g_prefix_key(self, key: str) -> bool:
        """Dispatch the key following the prompt ``g`` prefix.

        Returns ``True`` when *key* is a prompt-specific ``g`` continuation
        (handled here, even if the action is a context no-op) so the caller can
        fall through to vim's own ``g`` commands (``gg``, ``ge``/``gE``,
        ``gu``/``gU``/``g~``) for anything not in this table.  Dispatch is keyed
        from the same table that feeds the hint panel, but it intentionally does
        not consult hint availability: each action method keeps its own
        prompt-mode / multi-pane guards, so an unavailable continuation is a
        harmless swallowed no-op.
        """
        for binding in _PROMPT_G_PREFIX_BINDINGS:
            if binding.key != key:
                continue
            action = getattr(self, binding.action_name, None)
            if callable(action):
                action()
            return True
        return False

    def g_prefix_hint_entries(self) -> list[PromptGPrefixHintEntry]:
        """Return currently useful prompt ``g`` prefix entries for rendering."""
        entries: list[PromptGPrefixHintEntry] = []
        for binding in _PROMPT_G_PREFIX_BINDINGS:
            is_available = getattr(self, binding.availability_method_name)
            if not is_available():
                continue
            label = getattr(self, binding.label_method_name)()
            entries.append(PromptGPrefixHintEntry(binding.key, label))
        return entries

    def submit_active_pane(self) -> None:
        """Submit the active pane through the existing ``g<enter>`` path."""
        if self._mode != "prompt":
            return
        self.active_text_area().action_submit_prompt()

    def _g_focus_next_pane(self) -> None:
        """Focus the next/lower pane (the ``gj`` keymap)."""
        self.focus_relative(1, target_mode="normal")

    def _g_focus_prev_pane(self) -> None:
        """Focus the previous/higher pane (the ``gk`` keymap)."""
        self.focus_relative(-1, target_mode="normal")

    def _g_move_pane_down(self) -> None:
        """Move the active pane lower/later (the ``gJ`` keymap)."""
        self.move_active_pane(1, target_mode="normal")

    def _g_move_pane_up(self) -> None:
        """Move the active pane higher/earlier (the ``gK`` keymap)."""
        self.move_active_pane(-1, target_mode="normal")

    def _g_prefix_available_pane_nav(self) -> bool:
        """Whether ``gj``/``gk``/``gJ``/``gK`` apply to a real multi-pane stack."""
        return self._mode == "prompt" and len(self._stack) > 1

    def _g_prefix_available_submit_active(self) -> bool:
        """Whether ``g<enter>`` can submit the active prompt pane."""
        return self._mode == "prompt"

    def _g_prefix_available_add_pane(self) -> bool:
        """Whether ``g-`` can append a bottom pane (prompt mode only)."""
        return self._mode == "prompt"

    def _g_prefix_available_frontmatter(self) -> bool:
        """Whether ``g=`` can toggle the prompt frontmatter panel."""
        return self._mode == "prompt"

    def _g_prefix_available_stash_active(self) -> bool:
        """Whether ``gs`` would capture a non-empty active prompt pane."""
        if self._mode != "prompt":
            return False
        try:
            return bool(self.active_text_area().text.strip())
        except Exception:
            return bool(self._stack.selected_item.text.strip())

    def _g_prefix_available_stash_all(self) -> bool:
        """Whether ``gS`` would capture at least one pane in a real stack."""
        if self._mode != "prompt" or len(self._stack) <= 1:
            return False
        self._sync_state_from_widgets()
        return any(item.text.strip() for item in self._stack.items)

    def _g_prefix_available_stash_restore(self) -> bool:
        """Whether ``gp``/``gP`` have a restorable prompt stash in this app."""
        if self._mode != "prompt":
            return False
        try:
            checker = getattr(self.app, "_has_stashed_prompts", None)
            return bool(checker()) if callable(checker) else False
        except Exception:
            return False

    def _g_prefix_label_focus_next(self) -> str:
        """Return the ``gj`` label."""
        return "focus next pane"

    def _g_prefix_label_focus_prev(self) -> str:
        """Return the ``gk`` label."""
        return "focus prev pane"

    def _g_prefix_label_move_down(self) -> str:
        """Return the ``gJ`` label."""
        return "move pane down"

    def _g_prefix_label_move_up(self) -> str:
        """Return the ``gK`` label."""
        return "move pane up"

    def _g_prefix_label_submit_active(self) -> str:
        """Return the context-sensitive ``g<enter>`` label."""
        if len(self._stack) > 1:
            return "launch this pane"
        return "submit this draft"

    def _g_prefix_label_add_pane(self) -> str:
        """Return the ``g-`` label."""
        return "add pane"

    def _g_prefix_label_frontmatter(self) -> str:
        """Return the ``g=`` label."""
        return "toggle frontmatter"

    def _g_prefix_label_stash_active(self) -> str:
        """Return the context-sensitive ``gs`` label."""
        if len(self._stack) > 1:
            return "stash this pane"
        return "stash this draft"

    def _g_prefix_label_stash_all(self) -> str:
        """Return the ``gS`` label."""
        return "stash all panes"

    def _g_prefix_label_load_stash(self) -> str:
        """Return the ``gp`` label."""
        return "load stash…"

    def _g_prefix_label_restore_stash(self) -> str:
        """Return the ``gP`` label."""
        return "restore stash…"

    def focus_relative(self, delta: int, target_mode: str = "normal") -> bool:
        """Move pane focus by *delta* (the ``gk`` / ``gj`` keymaps).

        ``gk`` focuses the previous/higher pane (``delta`` ``-1``) and ``gj`` the
        next/lower pane (``delta`` ``+1``); focus cycles at the stack edges, so
        ``gk`` from the top pane wraps to the bottom and ``gj`` from the bottom
        wraps to the top.  Navigation is a pure focus change; no pane is
        rebuilt, so each pane keeps its cursor and edit state.  ``target_mode``
        ("normal" or "insert") selects the vim mode the newly active pane lands
        in; the pane-focus keys are normal-mode-only, so callers pass
        ``"normal"``.  Returns ``True`` when the selection moved.
        """
        if len(self._stack) <= 1:
            return False
        self._clear_active_completion_state()
        if not self._stack.move_focus(delta):
            return False
        self._apply_active_classes()
        text_area = self.active_text_area()
        text_area.focus()
        if target_mode == "insert":
            text_area._enter_insert_mode()
        else:
            text_area._enter_normal_mode()
        self._schedule_height_update()
        return True

    def move_active_pane(self, delta: int, target_mode: str = "normal") -> bool:
        """Reorder the active pane by *delta* (the ``gK`` / ``gJ`` keymaps).

        ``delta`` of ``-1`` moves the pane higher/earlier (``gK``) and ``+1``
        lower/later (``gJ``); reorder cycles at the stack edges, so ``gK`` from
        the top pane wraps it to the bottom and ``gJ`` from the bottom wraps it
        to the top.  The live pane texts are synced into the model first so the
        rebuild preserves what the user has typed; the moved pane stays active
        and lands in *target_mode* ("normal" or "insert").  Pane reorder is
        normal-mode-only, so callers pass ``"normal"``.  Returns ``True`` when it
        moved.
        """
        if len(self._stack) <= 1:
            return False
        self._sync_state_from_widgets()
        self._clear_active_completion_state()
        if not self._stack.move_selected(delta):
            return False
        self._rebuild_stack(enter_mode=target_mode)
        return True

    def add_bottom_pane(self) -> None:
        """Append a new empty bottom pane and drop into it (the ``g-`` keymap).

        Only meaningful in prompt mode; feedback / approve-prompt bars are not
        multi-agent surfaces, so it is a no-op elsewhere.  The new pane is
        focused in insert mode so the user can immediately type the next agent
        prompt, pushing the previous panes up.
        """
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        self._clear_active_completion_state()
        self._stack.append_bottom("")
        self._rebuild_stack(enter_mode="insert")

    def stash_active_pane(self) -> None:
        """Stash the active pane's draft for later (the ``gs`` keymap).

        Prompt mode only — feedback / approve-prompt bars are not stashable, so
        it is a no-op there.  The pane's stripped text + the bar's shared YAML
        frontmatter are captured into a single stash entry and the pane is
        removed; when it was the last pane the whole bar empties and the app
        unmounts it (``dismiss_bar``) through the post-submit path, which does
        *not* re-record the text as cancelled history.  An empty pane stashes
        nothing — an empty ``Stashed`` is posted so the app can toast a no-op.
        """
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        text = self._stack.selected_item.text.strip()
        if not text:
            self.post_message(self.Stashed([], source="current", dismiss_bar=False))
            return
        pane = StashedPromptPane(
            text=text,
            frontmatter=self._stack.frontmatter,
            pane_index=self._stack.selected_index,
        )
        self._clear_active_completion_state()
        removed = self._stack.remove_selected()
        self.post_message(
            self.Stashed([pane], source="current", dismiss_bar=not removed)
        )
        if removed:
            self._rebuild_stack(enter_mode="insert")

    def stash_all_panes(self) -> None:
        """Stash every non-empty pane in the bar (the ``gS`` keymap).

        Prompt mode only.  Each non-empty pane becomes its own stash entry —
        order preserved, original ``pane_index`` recorded — and all of them
        carry the bar's shared frontmatter, then the whole bar is dismissed
        (``dismiss_bar``).  When no pane has text it is a no-op and an empty
        ``Stashed`` is posted so the app can toast.
        """
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        panes = [
            StashedPromptPane(
                text=stripped,
                frontmatter=self._stack.frontmatter,
                pane_index=index,
            )
            for index, item in enumerate(self._stack.items)
            if (stripped := item.text.strip())
        ]
        if not panes:
            self.post_message(self.Stashed([], source="all", dismiss_bar=False))
            return
        self._clear_active_completion_state()
        self.post_message(self.Stashed(panes, source="all", dismiss_bar=True))

    def request_restore_stash(self) -> None:
        """Ask the app to open the destructive restore picker (the ``gP`` keymap).

        Presentation-only: the bar posts ``RestoreRequested`` (``destructive``)
        with its current mode and the app performs the snapshot read / pop / load
        (boundary rule D6).  Posted in every mode so the app can toast a no-op
        when restore is not available (feedback / approve-prompt bars).
        """
        self.post_message(self.RestoreRequested(self._mode, destructive=True))

    def request_load_stash(self) -> None:
        """Ask the app to load stash entries non-destructively (the ``gp`` keymap).

        Mirrors :meth:`request_restore_stash` but posts ``destructive=False`` so
        the app copies the chosen entries into the bar without removing them from
        the stash; the stash badge is left unchanged.
        """
        self.post_message(self.RestoreRequested(self._mode, destructive=False))

    def restore_stashed_entries(self, entries: list[tuple[str, str]]) -> None:
        """Append restored stash drafts as new panes (the ``gP`` restore path).

        Prompt mode only.  Each ``(text, frontmatter)`` becomes a new bottom
        pane, preserving any panes the user is already drafting.  The bar's
        shared frontmatter is adopted from the first restored entry that carries
        one when the bar has none yet.  A lone empty drafting pane is dropped so
        restored drafts don't sit beneath a blank pane.  The last restored pane
        is focused in insert mode so the user can keep editing.
        """
        if self._mode != "prompt" or not entries:
            return
        self._sync_state_from_widgets()
        self._clear_active_completion_state()
        drop_empty_lead = (
            len(self._stack) == 1 and not self._stack.selected_item.text.strip()
        )
        for text, frontmatter in entries:
            if frontmatter and not self._stack.frontmatter:
                self._stack.frontmatter = frontmatter
            self._stack.append_bottom(text)
        if drop_empty_lead:
            del self._stack.items[0]
            self._stack.selected_index = len(self._stack.items) - 1
        self._rebuild_stack(enter_mode="insert")

    def _clear_active_completion_state(self) -> None:
        """Drop transient active-pane state before stack focus/mutation."""
        try:
            text_area = self.active_text_area()
        except Exception:
            text_area = None
        if text_area is not None:
            text_area._clear_file_completion()
            text_area._clear_soft_completion(cancel_timer=True)
            text_area._clear_xprompt_arg_hint()
            text_area._clear_prompt_search(clear_highlights=True)
        self.hide_file_completions()
        self.hide_soft_completion()
