"""Prompt ``g`` prefix dispatch and hint metadata for PromptInputBar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.ace.tui.widgets._prompt_input_bar_stack_models import (
    PromptGPrefixHintEntry,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.widgets.prompt_stack import PromptStackState
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
else:
    _MixinBase = object


@dataclass(frozen=True)
class _PromptGPrefixBinding:
    """Declarative prompt ``g`` prefix binding metadata.

    One table drives both dispatch and the hint panel so the two cannot drift:
    ``action_name`` is the zero-arg method invoked on the second key,
    ``label_method_name`` renders the hint, and ``availability_method_name``
    gates whether the continuation is currently useful (and thus hinted).
    ``ctrl_g_only`` keeps a continuation on the prompt-local ``Ctrl+G`` surface
    without claiming the bare vim ``g`` prefix. ``ctrl_g_aliases`` adds alternate
    continuations to that surface without duplicating the action or hint row.
    """

    key: str
    action_name: str
    label_method_name: str
    availability_method_name: str
    uses_target_mode: bool = False
    ctrl_g_only: bool = False
    ctrl_g_aliases: tuple[str, ...] = ()


_PROMPT_G_PREFIX_BINDINGS: tuple[_PromptGPrefixBinding, ...] = (
    _PromptGPrefixBinding(
        "d",
        "edit_definition_under_cursor",
        "_g_prefix_label_definition",
        "_g_prefix_available_definition",
    ),
    _PromptGPrefixBinding(
        "f",
        "format_active_prompt",
        "_g_prefix_label_format_prompt",
        "_g_prefix_available_format_prompt",
    ),
    _PromptGPrefixBinding(
        "G",
        "request_open_glossary_panel",
        "_g_prefix_label_glossary",
        "_g_prefix_available_glossary",
    ),
    _PromptGPrefixBinding(
        "m",
        "request_open_memory_panel",
        "_g_prefix_label_memory",
        "_g_prefix_available_memory",
    ),
    _PromptGPrefixBinding(
        "enter",
        "submit_active_pane",
        "_g_prefix_label_submit_active",
        "_g_prefix_available_submit_active",
    ),
    _PromptGPrefixBinding(
        "ctrl+c",
        "action_cancel_all",
        "_g_prefix_label_cancel_all",
        "_g_prefix_available_cancel_all",
        ctrl_g_only=True,
    ),
    _PromptGPrefixBinding(
        "j",
        "_g_focus_next_pane",
        "_g_prefix_label_focus_next",
        "_g_prefix_available_pane_nav",
        uses_target_mode=True,
    ),
    _PromptGPrefixBinding(
        "k",
        "_g_focus_prev_pane",
        "_g_prefix_label_focus_prev",
        "_g_prefix_available_pane_nav",
        uses_target_mode=True,
    ),
    _PromptGPrefixBinding(
        "J",
        "_g_move_pane_down",
        "_g_prefix_label_move_down",
        "_g_prefix_available_pane_nav",
        uses_target_mode=True,
    ),
    _PromptGPrefixBinding(
        "K",
        "_g_move_pane_up",
        "_g_prefix_label_move_up",
        "_g_prefix_available_pane_nav",
        uses_target_mode=True,
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
        "stash_all_panes",
        "_g_prefix_label_stash_all",
        "_g_prefix_available_stash_all",
    ),
    _PromptGPrefixBinding(
        "S",
        "request_update_pinned_stash",
        "_g_prefix_label_update_pin",
        "_g_prefix_available_update_pin",
    ),
    _PromptGPrefixBinding(
        "t",
        "request_snippet_target_pane",
        "_g_prefix_label_snippet_target",
        "_g_prefix_available_snippet_target",
    ),
    _PromptGPrefixBinding(
        "T",
        "request_open_snippets_panel",
        "_g_prefix_label_snippets",
        "_g_prefix_available_snippets",
    ),
    _PromptGPrefixBinding(
        "w",
        "request_write_xprompt",
        "_g_prefix_label_write_xprompt",
        "_g_prefix_available_write_xprompt",
    ),
    _PromptGPrefixBinding(
        "x",
        "request_mini_xprompt_target_pane",
        "_g_prefix_label_mini_xprompt_target",
        "_g_prefix_available_mini_xprompt_target",
    ),
    _PromptGPrefixBinding(
        "X",
        "request_save_as_xprompt",
        "_g_prefix_label_save_xprompt",
        "_g_prefix_available_save_xprompt",
        ctrl_g_aliases=("ctrl+x",),
    ),
    _PromptGPrefixBinding(
        "L",
        "convert_active_pane_to_local_xprompt",
        "_g_prefix_label_convert_local_xprompt",
        "_g_prefix_available_convert_local_xprompt",
        uses_target_mode=True,
    ),
    _PromptGPrefixBinding(
        "p",
        "request_open_prompt_stash",
        "_g_prefix_label_open_stash",
        "_g_prefix_available_stash_restore",
        ctrl_g_only=True,
    ),
)


class PromptInputBarGPrefixActionsMixin(_MixinBase):
    """Prompt ``g`` prefix keymaps and hint entry generation."""

    if TYPE_CHECKING:
        _mode: str
        _stack: PromptStackState

        def _sync_state_from_widgets(self) -> None: ...
        def active_text_area(self) -> PromptTextArea: ...
        def action_cancel_all(self) -> None: ...
        def add_bottom_pane(self) -> None: ...
        def convert_active_pane_to_local_xprompt(
            self, *, target_mode: str = "normal"
        ) -> None: ...
        def focus_relative(self, delta: int, target_mode: str = "normal") -> bool: ...
        def move_active_pane(self, delta: int, target_mode: str = "normal") -> bool: ...
        def request_open_prompt_stash(self) -> None: ...
        def request_mini_xprompt_target_pane(self) -> None: ...
        def request_snippet_target_pane(self) -> None: ...
        def request_save_as_xprompt(self) -> None: ...
        def request_write_xprompt(self) -> None: ...
        def request_update_pinned_stash(self) -> None: ...
        def stash_all_panes(self) -> None: ...
        def toggle_frontmatter_panel(self) -> None: ...

    def dispatch_g_prefix_key(
        self,
        key: str,
        *,
        target_mode: str = "normal",
        via_ctrl_g: bool = False,
    ) -> bool:
        """Dispatch the key following the prompt ``g`` prefix.

        Returns ``True`` when *key* is a prompt-specific ``g`` continuation
        (handled here, even if the action is a context no-op) so the caller can
        fall through to vim's own ``g`` commands (``gg``, ``ge``/``gE``,
        ``gu``/``gU``/``g~``) for anything not in this table.  ``gm`` is claimed
        here and is unclaimed by the text area's vim ``g`` handling.  Dispatch
        is keyed from the same table that feeds the hint panel, but it
        intentionally does not consult hint availability: each action method
        keeps its own prompt-mode / multi-pane guards, so an unavailable
        continuation is a harmless swallowed no-op.  ``target_mode`` only
        affects pane focus / reorder continuations; normal-mode callers keep
        the default while insert-mode ``Ctrl+G`` callers can keep the
        destination pane in INSERT. ``via_ctrl_g`` exposes continuations that
        belong only to the ``Ctrl+G`` prefix, not bare vim ``g``.
        """
        for binding in _PROMPT_G_PREFIX_BINDINGS:
            if binding.key != key and not (
                via_ctrl_g and key in binding.ctrl_g_aliases
            ):
                continue
            if binding.ctrl_g_only and not via_ctrl_g:
                continue
            action = getattr(self, binding.action_name, None)
            if callable(action):
                if binding.uses_target_mode:
                    action(target_mode=target_mode)
                else:
                    action()
            return True
        return False

    def g_prefix_hint_entries(
        self, *, via_ctrl_g: bool = False
    ) -> list[PromptGPrefixHintEntry]:
        """Return currently useful prompt ``g`` prefix entries for rendering."""
        entries: list[PromptGPrefixHintEntry] = []
        for binding in _PROMPT_G_PREFIX_BINDINGS:
            if binding.ctrl_g_only and not via_ctrl_g:
                continue
            is_available = getattr(self, binding.availability_method_name)
            if not is_available():
                continue
            label = getattr(self, binding.label_method_name)()
            aliases = binding.ctrl_g_aliases if via_ctrl_g else ()
            entries.append(PromptGPrefixHintEntry(binding.key, label, aliases))
        return entries

    def submit_active_pane(self) -> None:
        """Submit the active pane through the existing ``g<enter>`` path."""
        if self._mode != "prompt":
            return
        self.active_text_area().action_submit_prompt()

    def edit_definition_under_cursor(self) -> None:
        """Open the xprompt definition at the cursor in the bound stack."""
        if self._mode != "prompt" or self._stack.selected_item.is_auxiliary_pane:
            return
        action = getattr(self.active_text_area(), "_edit_definition_under_cursor", None)
        if callable(action):
            action()

    def format_active_prompt(self) -> None:
        """Format the pane that is active when this action is invoked."""
        if self._stack.selected_item.is_auxiliary_pane:
            return
        text_area = self.active_text_area()
        if not text_area.text:
            return
        action = getattr(text_area, "format_prompt_markdown", None)
        if callable(action):
            action()

    def request_open_glossary_panel(self) -> None:
        """Ask the app to open the glossary panel.

        Presentation-only: the bar captures the glossary term under the
        cursor (if any) and posts ``GlossaryPanelRequested`` with that term
        and the bar's current mode. The app opens the panel and restores
        prompt focus and vim mode on dismiss (boundary rule D6).
        """
        self.post_message(
            self.GlossaryPanelRequested(  # type: ignore[attr-defined]
                self._glossary_term_under_cursor(),
                self._mode,
            )
        )

    def request_open_snippets_panel(self) -> None:
        """Ask the app to open the snippets panel.

        Presentation-only: the bar captures a bare snippet trigger or
        ``#[trigger]`` under the cursor (if any) without I/O and posts
        ``SnippetPanelRequested`` with that trigger and the bar's current
        mode. The app opens the panel and restores prompt focus, vim mode,
        selection, and cursor on dismiss (boundary rule D6).
        """
        self.post_message(
            self.SnippetPanelRequested(  # type: ignore[attr-defined]
                self._snippet_trigger_under_cursor(),
                self._mode,
            )
        )

    def _snippet_trigger_under_cursor(self) -> str | None:
        """Return the snippet trigger at the cursor, if resolvable without I/O."""
        try:
            from sase.snippet.cursor import snippet_trigger_at_offset

            text_area = self.active_text_area()
            offset = text_area._absolute_offset(text_area.cursor_location)
            known = getattr(self.app, "_snippets_cache", None)
            if not isinstance(known, dict):
                known = getattr(self.app, "_user_snippets", None)
            if not isinstance(known, dict):
                known = None
            return snippet_trigger_at_offset(text_area.text, offset, known)
        except Exception:
            return None

    def request_open_memory_panel(self) -> None:
        """Ask the app to open the memory panel.

        Presentation-only: the bar captures the ``#memory/<stem>`` xprompt
        reference under the cursor (if any) and posts
        ``MemoryPanelRequested`` with that reference and the bar's current
        mode. The app opens the panel and restores prompt focus and vim
        mode on dismiss (boundary rule D6).
        """
        self.post_message(
            self.MemoryPanelRequested(  # type: ignore[attr-defined]
                self._memory_note_under_cursor(),
                self._mode,
            )
        )

    def _glossary_term_under_cursor(self) -> str | None:
        """Return the highlighted glossary term at the cursor, if any.

        Reuses the prompt-area ``lookup_glossary_span`` match used by the
        glossary preview action. A cold or missing catalog is a miss: the
        panel loads its own catalog and opens on the first term.
        """
        try:
            match = self.active_text_area()._glossary_match_under_cursor(schedule=False)
        except Exception:
            return None
        if not isinstance(match, tuple) or len(match) != 3:
            return None
        term = getattr(match[2], "term", None)
        return term if isinstance(term, str) and term else None

    def _memory_note_under_cursor(self) -> str | None:
        """Return the ``#memory/<stem>`` reference at the cursor, if any.

        Reuses the prompt-area jump-target detection used by definition
        jumps. A non-memory xprompt, a nested path, or a miss is ``None``:
        the panel loads its own catalog and opens on the seeded scope's
        first note.
        """
        try:
            from sase.ace.tui.widgets._prompt_jump_target import (
                detect_jump_target_at_cursor,
            )

            text_area = self.active_text_area()
            offset = text_area._absolute_offset(text_area.cursor_location)
            target = detect_jump_target_at_cursor(text_area.text, offset)
        except Exception:
            return None
        if target is None or getattr(target, "kind", None) != "xprompt":
            return None
        name = str(getattr(target, "target", "") or "")
        if name.startswith("#"):
            name = name[1:]
        if not name.startswith("memory/"):
            return None
        stem = name.removeprefix("memory/")
        if stem.endswith(".md"):
            stem = stem[: -len(".md")]
        if not stem or "/" in stem or stem.lower() == "readme":
            return None
        return f"#memory/{stem}"

    def _g_focus_next_pane(self, *, target_mode: str = "normal") -> None:
        """Focus the next/lower pane (the ``gj`` keymap)."""
        self.focus_relative(1, target_mode=target_mode)

    def _g_focus_prev_pane(self, *, target_mode: str = "normal") -> None:
        """Focus the previous/higher pane (the ``gk`` keymap)."""
        self.focus_relative(-1, target_mode=target_mode)

    def _g_move_pane_down(self, *, target_mode: str = "normal") -> None:
        """Move the active pane lower/later (the ``gJ`` keymap)."""
        self.move_active_pane(1, target_mode=target_mode)

    def _g_move_pane_up(self, *, target_mode: str = "normal") -> None:
        """Move the active pane higher/earlier (the ``gK`` keymap)."""
        self.move_active_pane(-1, target_mode=target_mode)

    def _g_prefix_available_pane_nav(self) -> bool:
        """Whether ``gj``/``gk``/``gJ``/``gK`` apply to a real multi-pane stack."""
        return self._mode == "prompt" and len(self._stack) > 1

    def _g_prefix_available_submit_active(self) -> bool:
        """Whether ``g<enter>`` can submit the active prompt pane."""
        return self._mode == "prompt"

    def _g_prefix_available_definition(self) -> bool:
        if self._mode != "prompt" or self._stack.selected_item.is_auxiliary_pane:
            return False
        try:
            from sase.ace.tui.widgets._prompt_jump_target import (
                detect_jump_target_at_cursor,
            )

            text_area = self.active_text_area()
            offset = text_area._absolute_offset(text_area.cursor_location)
            known_skills = (
                text_area._get_warm_xprompt_skill_names()
                if "/" in text_area.text
                else frozenset()
            )
            target = detect_jump_target_at_cursor(
                text_area.text,
                offset,
                known_skills=known_skills,
            )
            return target is not None and target.kind == "xprompt"
        except Exception:
            return False

    def _g_prefix_available_format_prompt(self) -> bool:
        """Whether the active prompt-style pane contains text to format."""
        if self._stack.selected_item.is_auxiliary_pane:
            return False
        try:
            return bool(self.active_text_area().text.strip())
        except Exception:
            return False

    def _g_prefix_available_glossary(self) -> bool:
        """Whether ``gG`` / ``^GG`` can open the glossary panel."""
        return self._mode == "prompt"

    def _g_prefix_available_memory(self) -> bool:
        """Whether ``gm`` / ``^Gm`` can open the memory panel."""
        return self._mode == "prompt"

    def _g_prefix_available_snippets(self) -> bool:
        """Whether ``gT`` / ``^GT`` can open the snippets panel."""
        return self._mode == "prompt"

    def _g_prefix_available_cancel_all(self) -> bool:
        """Whether ``Ctrl+G Ctrl+C`` can cancel the whole prompt stack."""
        return self._mode == "prompt"

    def _g_prefix_available_add_pane(self) -> bool:
        """Whether ``g-`` can append a bottom pane (prompt mode only)."""
        return self._mode == "prompt"

    def _g_prefix_available_frontmatter(self) -> bool:
        """Whether ``g=`` can toggle the prompt frontmatter panel."""
        return self._mode == "prompt"

    def _g_prefix_available_stash_all(self) -> bool:
        """Whether ``gs`` would capture at least one pane in a real stack."""
        if self._mode != "prompt" or self._stack.agent_count <= 1:
            return False
        self._sync_state_from_widgets()
        return any(item.text.strip() for item in self._stack.agent_items)

    def _g_prefix_available_stash_restore(self) -> bool:
        """Whether ``Ctrl+G p`` has a restorable prompt stash in this app."""
        if self._mode != "prompt":
            return False
        try:
            checker = getattr(self.app, "_has_stashed_prompts", None)
            return bool(checker()) if callable(checker) else False
        except Exception:
            return False

    def _g_prefix_available_update_pin(self) -> bool:
        """Whether ``gS`` can save the current draft over a pinned stash."""
        if self._mode != "prompt":
            return False
        try:
            checker = getattr(self.app, "_has_pinned_stashed_prompts", None)
            has_pin = bool(checker()) if callable(checker) else False
        except Exception:
            return False
        if not has_pin:
            return False
        self._sync_state_from_widgets()
        return any(item.text.strip() for item in self._stack.agent_items)

    def _g_prefix_available_snippet_target(self) -> bool:
        """Whether ``gt`` can open or retarget a snippet target pane."""
        return self._mode == "prompt"

    def _g_prefix_available_mini_xprompt_target(self) -> bool:
        """Whether ``gx`` can open or retarget a mini-xprompt target pane."""
        return self._mode == "prompt"

    def _g_prefix_available_save_xprompt(self) -> bool:
        """Whether ``gX`` can open the whole-stack save-as panel."""
        if self._mode != "prompt":
            return False
        self._sync_state_from_widgets()
        return any(item.text.strip() for item in self._stack.agent_items) or bool(
            self._stack.frontmatter.strip()
        )

    def _g_prefix_available_write_xprompt(self) -> bool:
        if self._stack.selected_item.is_auxiliary_pane:
            return False
        return (
            self._stack.binding is not None and self._g_prefix_available_save_xprompt()
        )

    def _g_prefix_available_convert_local_xprompt(self) -> bool:
        """Whether ``gL`` can convert the active pane into a local xprompt.

        Prompt mode only, and only when the active pane has non-blank text —
        the conversion stores that pane body as a local ``xprompts:`` helper, so
        an empty pane has nothing to save.
        """
        if self._mode != "prompt":
            return False
        self._sync_state_from_widgets()
        if self._stack.selected_item.is_auxiliary_pane:
            return False
        return bool(self._stack.selected_item.text.strip())

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
        if self._stack.selected_item.is_snippet_pane:
            return "save snippet"
        if self._stack.selected_item.is_mini_xprompt_pane:
            return "save mini-xprompt"
        if self._stack.agent_count > 1:
            return "launch this pane"
        return "submit this draft"

    def _g_prefix_label_definition(self) -> str:
        return "edit definition"

    def _g_prefix_label_format_prompt(self) -> str:
        return "format prompt"

    def _g_prefix_label_glossary(self) -> str:
        return "glossary…"

    def _g_prefix_label_memory(self) -> str:
        return "memory…"

    def _g_prefix_label_snippets(self) -> str:
        return "snippets…"

    def _g_prefix_label_cancel_all(self) -> str:
        """Return the ``Ctrl+G Ctrl+C`` label."""
        return "cancel all panes"

    def _g_prefix_label_add_pane(self) -> str:
        """Return the ``g-`` label."""
        return "add pane"

    def _g_prefix_label_frontmatter(self) -> str:
        """Return the ``g=`` label."""
        return "toggle frontmatter"

    def _g_prefix_label_stash_all(self) -> str:
        """Return the ``gs`` label."""
        return "stash all panes"

    def _g_prefix_label_update_pin(self) -> str:
        """Return the ``gS`` label."""
        return "update pinned stash"

    def _g_prefix_label_snippet_target(self) -> str:
        """Return the ``gt`` label."""
        snippet = self._stack.snippet_item
        if snippet is not None and snippet.snippet_target is not None:
            return f"rename ⇥ {snippet.snippet_target.trigger}…"
        return "new snippet…"

    def _g_prefix_label_mini_xprompt_target(self) -> str:
        """Return the ``gx`` label."""
        mini = self._stack.mini_xprompt_item
        if mini is not None and mini.mini_xprompt_target is not None:
            return f"retarget #{mini.mini_xprompt_target.name}…"
        return "open mini-xprompt…"

    def _g_prefix_label_save_xprompt(self) -> str:
        """Return the ``gX`` label."""
        return "save as xprompt/snippet"

    def _g_prefix_label_write_xprompt(self) -> str:
        readonly = getattr(self, "_readonly_xprompt_target", None)
        if readonly is not None:
            return f"save as {readonly.reference}"
        binding = self._stack.binding
        if binding is not None:
            return f"save {binding.reference}"
        return "save as xprompt"

    def _g_prefix_label_convert_local_xprompt(self) -> str:
        """Return the ``gL`` label."""
        return "save as local xprompt"

    def _g_prefix_label_open_stash(self) -> str:
        """Return the ``Ctrl+G p`` label."""
        return "stashed prompts…"
