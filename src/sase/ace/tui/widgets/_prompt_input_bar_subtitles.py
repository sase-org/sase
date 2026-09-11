"""Subtitle and placeholder text for ``PromptInputBar``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets.prompt_stack import PromptStackState

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object


class PromptInputBarSubtitlesMixin(_MixinBase):
    """Prompt subtitle and empty-pane placeholder helpers."""

    if TYPE_CHECKING:
        _mode: str
        _stack: PromptStackState

        def _target_hint_reference(self) -> str | None: ...
        def _target_save_hint(self) -> str: ...

    def _snippet_pane_trigger(self) -> str | None:
        """Return the active pane's snippet trigger, or ``None`` off the snippet pane."""
        if self._mode != "prompt":
            return None
        item = self._stack.selected_item
        if not item.is_snippet_pane or item.snippet_target is None:
            return None
        return item.snippet_target.trigger

    def _mini_xprompt_pane_name(self) -> str | None:
        """Return the active pane's mini-xprompt name, or ``None`` off it."""
        if self._mode != "prompt":
            return None
        item = self._stack.selected_item
        if not item.is_mini_xprompt_pane or item.mini_xprompt_target is None:
            return None
        return item.mini_xprompt_target.name

    def insert_mode_subtitle(self) -> str:
        """Return the insert-mode subtitle, advertising the stack when stacked.

        ``<enter>`` opens the submit chooser for stacked or targeted prompts.
        A multi-pane stack swaps the ``[Esc] normal`` hint for ``[Esc] nav``
        and adds ``[^S] stash`` plus ``[^G Enter] this`` hints for active-pane
        actions.  ``Esc`` still drops into NORMAL mode for the normal ``g``
        prefix; INSERT mode reaches the same prompt-local actions through the
        ``Ctrl+G`` prefix.  The pinned snippet pane advertises its own save /
        discard / rename hints instead -- never the agent-stack hints, since
        ``<enter>`` means something completely different there.
        """
        trigger = self._snippet_pane_trigger()
        if trigger is not None:
            return (
                f"[Enter] save ⇥ {trigger}  [Esc] normal  [^C] discard  [^G t] rename"
            )
        mini_name = self._mini_xprompt_pane_name()
        if mini_name is not None:
            return (
                f"[Enter] save #{mini_name}  [Esc] normal  [^C] discard  "
                "[^G x] retarget  [^G =] properties"
            )
        target_hint = self._target_save_hint()
        if self._mode == "prompt" and self._stack.agent_count > 1:
            return (
                "[Enter] submit…  [Esc] nav  [^C] cancel  [^S] stash  "
                f"[^G Enter] this{target_hint}"
            )
        if self._mode == "prompt" and self._target_hint_reference() is not None:
            return f"[Enter] submit…  [Esc] normal  [^C] cancel{target_hint}"
        return "[Enter] send  [Esc] normal  [^C] cancel"

    def normal_mode_subtitle(self) -> str:
        """Return the normal-mode subtitle, advertising the stack keys.

        In a multi-pane stack the active pane's normal-mode hints surface the
        prompt-stack selected-pane submit (``g<enter>``), pane-focus
        (``gj``/``gk``) and reorder (``gJ``/``gK``) keys, plus the ``g`` prefix
        stash-all key (``gs``) and ``<Ctrl+S>`` active-pane stash.  A single-pane
        prompt bar still advertises ``g<enter>`` and ``<Ctrl+S>``; feedback /
        approve-prompt bars keep the original normal-mode hints since they are
        not stashable.  The full ``g`` prefix, including add-pane and
        frontmatter actions, is discoverable through the hint panel.  The
        pinned snippet pane advertises its own save / discard / rename hints
        instead, matching the insert-mode variant.
        """
        trigger = self._snippet_pane_trigger()
        if trigger is not None:
            return (
                f"[g<enter>] save ⇥ {trigger}  [i] insert  [^C] discard  [^G t] rename"
            )
        mini_name = self._mini_xprompt_pane_name()
        if mini_name is not None:
            return (
                f"[g<enter>] save #{mini_name}  [i] insert  [^C] discard  "
                "[^G x] retarget  [^G =] properties"
            )
        target_hint = self._target_save_hint()
        if self._mode == "prompt" and self._stack.agent_count > 1:
            return (
                "[g<enter>] launch  [gj/gk] pane  [gJ/gK] move  "
                f"[^S/gs] stash{target_hint}"
            )
        if self._mode == "prompt":
            return (
                "[Esc] clear  [i] insert  [g<enter>] send  [^S] stash  "
                f"[^C] cancel{target_hint}"
            )
        return "[Esc] clear  [i] insert  [^C] cancel"

    def _compute_placeholder(self) -> str:
        """Return the empty-pane placeholder text for the current mode."""
        if self._mode == "feedback":
            return "Type plan feedback...  [^G g] editor  [^J] newline"
        if self._mode == "approve_prompt":
            return "Type coder prompt...  [^G g] editor  [^J] newline"
        return (
            "Type prompt  [^K] history  [^T] complete  [^R] find  "
            "[^G g] editor  [^Y] workflow  [^J] newline"
        )
