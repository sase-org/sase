"""Xprompt syntax highlighting overlay for ``PromptTextArea``."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from rich.style import Style
from textual.widgets._text_area import TextAreaTheme

from sase.ace.tui.widgets._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from sase.xprompt.highlight import HighlightSpan, highlight_spans
from sase.xprompt.highlight_theme import (
    derive_argument_color,
    xprompt_argument_palette,
)

_INVALID_ARGUMENT_VALIDITIES = frozenset(
    {"unknown_key", "type_mismatch", "duplicate_key"}
)

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase

    from sase.ace.tui.widgets.xprompt_arg_assist import XPromptAssistEntry
else:
    _MixinBase = object


class XPromptSyntaxHighlightMixin(_MixinBase):
    """Overlay recognized xprompt syntax on TextArea markdown highlighting."""

    if TYPE_CHECKING:
        _xprompt_highlight_skill_entries: list[XPromptAssistEntry] | None
        _xprompt_highlight_skill_names: frozenset[str]

        def _append_highlight_span(
            self,
            start: int,
            end: int,
            style_name: str,
        ) -> None: ...
        def _get_warm_xprompt_arg_assist_entries(
            self,
        ) -> list[XPromptAssistEntry] | None: ...
        def _get_exact_warm_xprompt_arg_assist_entries(
            self,
        ) -> list[XPromptAssistEntry] | None: ...

    def on_mount(self) -> None:
        """Register xprompt styles after the base Jinja theme exists."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._register_xprompt_text_area_theme()

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        self._register_xprompt_text_area_theme()

    def _register_jinja_text_area_theme(self) -> None:
        register_jinja = getattr(super(), "_register_jinja_text_area_theme", None)
        if callable(register_jinja):
            register_jinja()
        self._register_xprompt_text_area_theme(_JINJA_THEME_NAME, apply=False)

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        text = self.text
        has_slash = "/" in text
        if "#" not in text and "%" not in text and "---" not in text and not has_slash:
            return
        if len(text.encode("utf-8")) > _MAX_OVERLAY_BYTES:
            return
        if text.count("\n") > _MAX_OVERLAY_LINES:
            return

        try:
            entries = self._get_exact_warm_xprompt_arg_assist_entries()
            known_skills = (
                self._xprompt_skill_names_from_entries(entries)
                if has_slash and entries is not None
                else frozenset()
            )
            spans = highlight_spans(
                text,
                known_skills=known_skills,
                xprompt_arg_assist_entries=entries,
            )
        except Exception:
            return
        for span in spans:
            if not span.role.startswith("xprompt."):
                continue
            self._append_highlight_span(
                span.start,
                span.end,
                _text_area_style_name(span),
            )

    def _get_warm_xprompt_skill_names(self) -> frozenset[str]:
        """Return memoized skill names from the disk-free warm catalog."""
        return self._get_warm_xprompt_skill_names_if_available() or frozenset()

    def _get_warm_xprompt_skill_names_if_available(
        self,
    ) -> frozenset[str] | None:
        """Return memoized skill names, preserving a cold-catalog sentinel."""
        entries = self._get_exact_warm_xprompt_arg_assist_entries()
        if entries is None:
            return None
        return self._xprompt_skill_names_from_entries(entries)

    def _xprompt_skill_names_from_entries(
        self,
        entries: list[XPromptAssistEntry],
    ) -> frozenset[str]:
        """Return memoized skill names for an already-warm catalog entry list."""
        if entries is self._xprompt_highlight_skill_entries:
            return self._xprompt_highlight_skill_names
        # Highlight ``/foo`` by the provider skill name; ``entry.name`` is the
        # namespaced ``skill/foo`` xprompt reference.
        names = frozenset(
            entry.skill_name for entry in entries if entry.is_skill and entry.skill_name
        )
        self._xprompt_highlight_skill_entries = entries
        self._xprompt_highlight_skill_names = names
        return names

    def _register_xprompt_text_area_theme(
        self,
        theme_name: str | None = None,
        *,
        apply: bool = True,
    ) -> None:
        active_name = theme_name or str(getattr(self, "theme", "css") or "css")
        base = self._resolve_xprompt_base_theme(active_name)
        syntax_styles = dict(base.syntax_styles)
        app_theme = self.app.current_theme
        background = app_theme.background or "#000000"
        argument_colors = xprompt_argument_palette(
            app_theme.success,
            foreground=app_theme.foreground,
            background=background,
            secondary=app_theme.secondary,
            accent=app_theme.accent,
            primary=app_theme.primary,
        )
        syntax_styles.update(
            {
                "xprompt.invocation": Style(
                    color=app_theme.success,
                    bold=True,
                ),
                "xprompt.invocation_arg": Style(
                    color=derive_argument_color(
                        app_theme.success,
                        foreground=app_theme.foreground,
                        background=background,
                    )
                ),
                "xprompt.directive": Style(
                    color=app_theme.warning,
                    bold=True,
                ),
                "xprompt.directive_arg": Style(
                    color=derive_argument_color(
                        app_theme.warning,
                        foreground=app_theme.foreground,
                        background=background,
                    )
                ),
                "xprompt.arg_delimiter": Style(
                    color=argument_colors["xprompt.arg_delimiter"],
                ),
                "xprompt.arg_key": Style(
                    color=argument_colors["xprompt.arg_key"],
                ),
                "xprompt.arg_assign": Style(
                    color=argument_colors["xprompt.arg_assign"],
                ),
                "xprompt.arg_value": Style(
                    color=argument_colors["xprompt.arg_value"],
                ),
                "xprompt.arg_value_string": Style(
                    color=argument_colors["xprompt.arg_value_string"],
                ),
                "xprompt.arg_value_number": Style(
                    color=argument_colors["xprompt.arg_value_number"],
                ),
                "xprompt.arg_value_bool": Style(
                    color=argument_colors["xprompt.arg_value_bool"],
                ),
                "xprompt.separator": Style(
                    color=app_theme.secondary,
                    dim=True,
                    bold=True,
                ),
                "xprompt.skill": Style(
                    color=derive_argument_color(
                        app_theme.accent,
                        foreground=app_theme.foreground,
                        background=background,
                    ),
                    bold=True,
                ),
            }
        )
        for role, color in argument_colors.items():
            syntax_styles[f"{role}.invalid"] = Style(color=color, underline=True)
        theme = dataclasses.replace(
            base,
            name=active_name,
            syntax_styles=syntax_styles,
        )
        self.register_theme(theme)
        if apply:
            self._set_theme(theme.name)

    def _resolve_xprompt_base_theme(self, theme_name: str) -> TextAreaTheme:
        try:
            theme: TextAreaTheme | None = self._themes[theme_name]
        except KeyError:
            theme = TextAreaTheme.get_builtin_theme(theme_name)
        if theme is None:
            fallback = TextAreaTheme.get_builtin_theme("css")
            assert fallback is not None
            return fallback
        return theme


def _text_area_style_name(span: HighlightSpan) -> str:
    if (
        span.role.startswith("xprompt.arg_")
        and span.validity in _INVALID_ARGUMENT_VALIDITIES
    ):
        return f"{span.role}.invalid"
    return span.role
