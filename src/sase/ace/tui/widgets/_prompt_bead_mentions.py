"""Status-tinted bead-mention highlighting for prompts."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from textual.widgets._text_area import TextAreaTheme

from sase.ace.tui.util.semantic_styles import (
    bead_mention_style_name,
    semantic_highlight_styles_from_theme,
)
from sase.ace.tui.widgets._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from sase.bead.mentions import scan_bead_mentions

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase

    from sase.ace.tui.models.bead_preview import (
        BeadMentionIndex,
        BeadStoreDirectory,
    )
    from sase.bead.mentions import BeadMention
else:
    _MixinBase = object


class PromptBeadMentionMixin(_MixinBase):
    """Memory-only status-tinted bead overlay for ``PromptTextArea``.

    Bare bead IDs that resolve to a known status get a bold, underlined
    span in that status's color (``bead.mention.<status>``), so the ``K``
    affordance is visible before it is pressed. Unknown and missing IDs
    stay plain. ``@bead:`` refs keep the artifact-ref overlay's styling.

    The render path only reads the warm store directory and the app-level
    mention index: no scheduling, no I/O, never per keystroke. Resolution
    runs off-thread on discrete triggers only (prompt mount, directory
    publish, NORMAL-mode entry, ``K``/``Ctrl+]``).
    """

    if TYPE_CHECKING:
        _prompt_bead_mention_scan_directory: int | None
        _prompt_bead_mention_scan_index: int | None
        _prompt_bead_mention_scan_text: str | None
        _prompt_bead_mention_cached: tuple[BeadMention, ...] | None

        def _append_highlight_span(
            self,
            start: int,
            end: int,
            style_name: str,
        ) -> None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # TextArea builds its first highlight map inside its constructor, so
        # this cache must exist before delegating to the base widget.
        self._prompt_bead_mention_scan_directory: int | None = None
        self._prompt_bead_mention_scan_index: int | None = None
        self._prompt_bead_mention_scan_text: str | None = None
        self._prompt_bead_mention_cached: tuple[BeadMention, ...] | None = None
        super().__init__(*args, **kwargs)

    def _prompt_mount_hook(self) -> None:
        """Warm the directory, register styles, and resolve current mentions."""
        super_hook = getattr(super(), "_prompt_mount_hook", None)
        if callable(super_hook):
            super_hook()
        self._register_bead_mention_text_area_theme()
        directory = self._bead_store_directory_for_action(schedule=True)
        del directory
        self._request_bead_mention_resolution_for_text()

    def _enter_normal_mode(self) -> None:
        """Resolve mentions on leaving INSERT mode (finished typing)."""
        super_hook = getattr(super(), "_enter_normal_mode", None)
        if callable(super_hook):
            super_hook()
        try:
            self._request_bead_mention_resolution_for_text()
        except Exception:
            pass

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        self._register_bead_mention_text_area_theme()

    def _register_jinja_text_area_theme(self) -> None:
        register_jinja = getattr(super(), "_register_jinja_text_area_theme", None)
        if callable(register_jinja):
            register_jinja()
        self._register_bead_mention_text_area_theme(_JINJA_THEME_NAME, apply=False)

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        text = self.text
        if not text.strip():
            return
        if len(text.encode("utf-8")) > _MAX_OVERLAY_BYTES:
            return
        if text.count("\n") > _MAX_OVERLAY_LINES:
            return

        try:
            mentions = self._prompt_bead_mentions_for_render(text)
            index = self._bead_mention_index_for_render()
        except Exception:
            return
        if not mentions or index is None:
            return
        for mention in mentions:
            if mention.form != "bare":
                continue
            try:
                entry = index.peek(mention.bead_id)
            except Exception:
                continue
            if entry is None or entry.status is None:
                continue
            self._append_highlight_span(
                mention.start, mention.end, bead_mention_style_name(entry.status)
            )

    def _prompt_bead_mentions_for_render(
        self,
        text: str,
    ) -> tuple[BeadMention, ...]:
        """Scan owned-prefix mentions, cached by (text, directory, index)."""
        directory = self._bead_store_directory_for_action(schedule=False)
        if directory is None:
            return ()
        index = self._bead_mention_index_for_render()
        directory_key: int | None = None
        index_key: int | None = None
        try:
            directory_key = id(directory)
            index_key = id(index) if index is not None else None
        except Exception:
            directory_key = None
            index_key = None
        if (
            self._prompt_bead_mention_scan_text == text
            and self._prompt_bead_mention_scan_directory == directory_key
            and self._prompt_bead_mention_scan_index == index_key
            and self._prompt_bead_mention_cached is not None
        ):
            return self._prompt_bead_mention_cached
        try:
            prefixes = directory.owned_prefixes()
        except Exception:
            return ()
        try:
            mentions = scan_bead_mentions(text, prefixes)
        except Exception:
            return ()
        self._prompt_bead_mention_scan_text = text
        self._prompt_bead_mention_scan_directory = directory_key
        self._prompt_bead_mention_scan_index = index_key
        self._prompt_bead_mention_cached = mentions
        return mentions

    def _request_bead_mention_resolution_for_text(self) -> None:
        """Queue unresolved owned-prefix mention IDs (memory only, no I/O)."""
        app = self._active_app()
        if app is None:
            return
        requester = getattr(app, "request_bead_mention_resolution", None)
        if not callable(requester):
            return
        directory = self._bead_store_directory_for_action(schedule=False)
        if directory is None:
            return
        index = self._bead_mention_index_for_render()
        try:
            text = self.text
        except Exception:
            return
        if not text.strip():
            return
        try:
            mentions = scan_bead_mentions(text, directory.owned_prefixes())
        except Exception:
            return
        if not mentions:
            return
        unresolved = [
            mention.bead_id
            for mention in mentions
            if index is None or index.peek(mention.bead_id) is None
        ]
        if not unresolved:
            return
        try:
            requester(unresolved)
        except Exception:
            pass

    def _bead_store_directory_for_action(
        self,
        *,
        schedule: bool = False,
    ) -> BeadStoreDirectory | None:
        app = self._active_app()
        if app is None:
            return None
        getter = getattr(app, "get_bead_store_directory", None)
        if not callable(getter):
            return None
        try:
            value = getter(schedule=schedule)
        except Exception:
            return None
        return value

    def _bead_mention_index_for_render(self) -> BeadMentionIndex | None:
        app = self._active_app()
        if app is None:
            return None
        getter = getattr(app, "bead_mention_index_for_render", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            return None

    def _active_app(self) -> Any | None:
        try:
            return self.app
        except Exception:
            return None

    def _register_bead_mention_text_area_theme(
        self,
        theme_name: str | None = None,
        *,
        apply: bool = True,
    ) -> None:
        active_name = theme_name or str(getattr(self, "theme", "css") or "css")
        base = self._resolve_bead_mention_base_theme(active_name)
        syntax_styles = dict(base.syntax_styles)
        styles = semantic_highlight_styles_from_theme(self.app.current_theme)
        if styles is not None:
            for status, style in styles.bead.items():
                syntax_styles[bead_mention_style_name(status)] = style
        theme = dataclasses.replace(
            base,
            name=active_name,
            syntax_styles=syntax_styles,
        )
        self.register_theme(theme)
        if apply:
            self._set_theme(theme.name)

    def _resolve_bead_mention_base_theme(self, theme_name: str) -> TextAreaTheme:
        try:
            theme: TextAreaTheme | None = self._themes[theme_name]
        except KeyError:
            theme = TextAreaTheme.get_builtin_theme(theme_name)
        if theme is None:
            fallback = TextAreaTheme.get_builtin_theme("css")
            assert fallback is not None
            return fallback
        return theme


__all__ = [
    "PromptBeadMentionMixin",
]
