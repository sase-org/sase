"""PromptTextArea bridge to its parent ``PromptInputBar``.

Everything the prompt pane routes through the bar it lives in -- the bar lookup
itself, the undo/redo host notifications, the vim mode display, and the
``g``-prefix hint panels -- lives here, at the base of the actions mixin chain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.ace.tui.widgets.vim_text_area import VimTextArea as _MixinBase

    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
else:
    _MixinBase = object


def prompt_bar_class() -> type[PromptInputBar]:
    """Lazy import to avoid circular dependency with prompt_input_bar."""
    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

    return PromptInputBar


class PromptTextAreaBarMixin(_MixinBase):
    """Parent-bar lookup plus the host hooks that are routed through it."""

    if TYPE_CHECKING:
        _insert_g_prefix_pending: bool
        _normal_g_prefix_pending: bool
        _vim_mode: str

    def _find_prompt_bar(self) -> Any:
        """Walk up the widget tree to find the parent PromptInputBar."""
        PromptInputBar = prompt_bar_class()
        parent = self.parent
        while parent is not None:
            if isinstance(parent, PromptInputBar):
                return parent
            parent = parent.parent
        return None

    def _notify_host_text_undo(self, before_text: str, after_text: str) -> None:
        """Tell the parent bar a NORMAL-mode undo changed this pane's text.

        Lets the bar unstage xprompt inputs an inline expansion auto-staged when
        (and only when) this undo reversed that expansion's body splice. A pane
        with no parent bar -- or an undo that matches no expansion transaction --
        is a no-op. Overrides :class:`VimTextArea`'s no-op host hook.
        """
        bar = self._find_prompt_bar()
        if bar is None:
            return
        handler = getattr(bar, "handle_text_area_undo", None)
        if callable(handler):
            handler(self, before_text, after_text)

    def _notify_host_text_redo(self, before_text: str, after_text: str) -> None:
        """Tell the parent bar a NORMAL-mode redo changed this pane's text."""
        bar = self._find_prompt_bar()
        if bar is None:
            return
        handler = getattr(bar, "handle_text_area_redo", None)
        if callable(handler):
            handler(self, before_text, after_text)

    def _update_vim_mode_display(self, indicator: str = "") -> None:
        """Route the vim mode + pending indicator to the parent ``PromptInputBar``.

        Overrides :class:`VimTextArea`'s border-based default. Reproduces the
        prompt bar's per-mode chrome: NORMAL shows the stack-aware
        ``normal_mode_subtitle`` plus any pending indicator; VISUAL / V-LINE show
        the selection hints; INSERT shows the (title-suffix-free)
        ``insert_mode_subtitle``. A pane with no parent bar is a no-op.
        """
        bar = self._find_prompt_bar()
        if bar is None:
            return
        mode = self._vim_mode
        if mode in ("visual", "visual_line"):
            title = "[V-LINE]" if mode == "visual_line" else "[VISUAL]"
            bar._refresh_title(title)
            subtitle = "[Esc] normal  [o] swap ends  [^C] cancel"
            if indicator:
                subtitle += f"  {indicator}"
        elif mode == "insert":
            bar._refresh_title()
            subtitle = bar.insert_mode_subtitle()
        else:
            bar._refresh_title("[NORMAL]")
            # Derive the base from the bar so a stacked prompt keeps advertising
            # its stack keymaps while a count/operator/``g`` prefix is pending.
            base = "[Esc] clear  [i] insert  [^C] cancel"
            getter = getattr(bar, "normal_mode_subtitle", None)
            if callable(getter):
                base = getter()
            subtitle = f"{base}  {indicator}" if indicator else base
        setter = getattr(bar, "set_prompt_mode_subtitle", None)
        if callable(setter):
            setter(subtitle)
        else:
            bar.border_subtitle = subtitle

    def _dispatch_host_g_prefix_key(self, key: str) -> bool:
        """Forward a pending ``g<key>`` to the parent bar's stack dispatcher."""
        bar = self._find_prompt_bar()
        dispatch = (
            getattr(bar, "dispatch_g_prefix_key", None) if bar is not None else None
        )
        if callable(dispatch):
            return bool(dispatch(key))
        return False

    def _show_pending_g_hints(self) -> None:
        """Reveal the parent bar's vim ``g``-prefix continuation hint panel."""
        bar = self._find_prompt_bar()
        if bar is None:
            return
        show = getattr(bar, "show_g_prefix_hints", None)
        if callable(show):
            show()

    def _hide_pending_g_hints(self) -> None:
        """Hide the parent bar's vim ``g``-prefix continuation hint panel."""
        bar = self._find_prompt_bar()
        if bar is None:
            return
        hide = getattr(bar, "hide_g_prefix_hints", None)
        if callable(hide):
            hide()

    def _show_insert_g_prefix_hints(self) -> None:
        """Reveal prompt-local ``Ctrl+G`` continuation hints for INSERT mode."""
        bar = self._find_prompt_bar()
        if bar is None:
            return
        show = getattr(bar, "show_g_prefix_hints", None)
        if callable(show):
            show(prefix_label="^G", include_editor=True)

    def _clear_insert_g_prefix(self) -> None:
        """Clear any pending INSERT-mode ``Ctrl+G`` prefix and hide its hints."""
        if not self._insert_g_prefix_pending:
            return
        self._insert_g_prefix_pending = False
        bar = self._find_prompt_bar()
        if bar is None:
            return
        hide = getattr(bar, "hide_g_prefix_hints", None)
        if callable(hide):
            hide()

    def _show_normal_g_prefix_hints(self) -> None:
        """Reveal prompt-local ``Ctrl+G`` continuation hints for NORMAL mode.

        NORMAL-mode ``Ctrl+G`` shares the INSERT-mode ``Ctrl+G`` hint surface
        (the ``^G`` prefix label and the editor continuation), only differing in
        the vim mode it lives in and the ``target_mode`` it later dispatches.
        """
        bar = self._find_prompt_bar()
        if bar is None:
            return
        show = getattr(bar, "show_g_prefix_hints", None)
        if callable(show):
            show(prefix_label="^G", include_editor=True)

    def _clear_normal_g_prefix(self) -> None:
        """Clear any pending NORMAL-mode ``Ctrl+G`` prefix and hide its hints."""
        if not self._normal_g_prefix_pending:
            return
        self._normal_g_prefix_pending = False
        bar = self._find_prompt_bar()
        if bar is None:
            return
        hide = getattr(bar, "hide_g_prefix_hints", None)
        if callable(hide):
            hide()
