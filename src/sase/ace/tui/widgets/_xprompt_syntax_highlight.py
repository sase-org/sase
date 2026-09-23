"""Xprompt syntax highlighting overlay for ``PromptTextArea``."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import TYPE_CHECKING

from rich.style import Style
from textual.widgets._text_area import TextAreaTheme

from sase.xprompt import highlight as xprompt_highlight
from sase.ace.tui.widgets._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from sase.xprompt.highlight import (
    HighlightSpan,
    XPromptArgumentSource,
    XPromptHighlightRole,
    highlight_spans,
)
from sase.project_accents import PROJECT_ACCENTS
from sase.xprompt.highlight_theme import (
    derive_argument_color,
    xprompt_argument_palette,
)

_PROJECT_TAG_ROLES = frozenset(
    {
        "xprompt.project_tag.sigil",
        "xprompt.project_tag.name",
        "xprompt.project_tag.unknown",
    }
)

_INVALID_ARGUMENT_VALIDITIES = frozenset(
    {"unknown_key", "type_mismatch", "duplicate_key"}
)
_ARGUMENT_ROLES = frozenset(
    {
        "xprompt.arg_delimiter",
        "xprompt.arg_key",
        "xprompt.arg_assign",
        "xprompt.arg_value",
        "xprompt.arg_value_string",
        "xprompt.arg_value_number",
        "xprompt.arg_value_bool",
    }
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
        _xprompt_highlight_arg_entries: list[XPromptAssistEntry] | None
        _xprompt_highlight_arg_entries_wire: list[dict[str, object]] | None

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
        if (
            "#" not in text
            and "%" not in text
            and "---" not in text
            and "+" not in text
            and not has_slash
        ):
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
            wire_entries = (
                self._xprompt_arg_assist_entries_wire(entries)
                if entries is not None
                else None
            )
            spans = highlight_spans(
                text,
                known_skills=known_skills,
                xprompt_arg_assist_entries=entries,
                xprompt_arg_assist_entries_wire=wire_entries,
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

    def _xprompt_arg_assist_entries_wire(
        self,
        entries: list[XPromptAssistEntry],
    ) -> list[dict[str, object]]:
        """Return cached Rust-binding wire data for an unchanged warm catalog."""
        if entries is getattr(self, "_xprompt_highlight_arg_entries", None):
            cached = getattr(self, "_xprompt_highlight_arg_entries_wire", None)
            if cached is not None:
                return cached
        wire = xprompt_highlight.xprompt_arg_assist_entries_to_wire(entries)
        self._xprompt_highlight_arg_entries = entries
        self._xprompt_highlight_arg_entries_wire = wire
        return wire

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
        xprompt_argument_colors = xprompt_argument_palette(
            app_theme.success,
            foreground=app_theme.foreground,
            background=background,
            secondary=app_theme.secondary,
            accent=app_theme.accent,
            primary=app_theme.primary,
        )
        directive_argument_colors = xprompt_argument_palette(
            app_theme.warning,
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
        _update_argument_syntax_styles(
            syntax_styles,
            xprompt_argument_colors,
            source="xprompt",
        )
        _update_argument_syntax_styles(
            syntax_styles,
            directive_argument_colors,
            source="directive",
        )
        _update_project_tag_syntax_styles(syntax_styles, app_theme.warning)
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
    if span.role in _PROJECT_TAG_ROLES:
        return _project_tag_style_name(span.role, span.accent)
    style_name = _argument_style_name(span.role, span.source)
    if span.role in _ARGUMENT_ROLES and span.validity in _INVALID_ARGUMENT_VALIDITIES:
        return f"{style_name}.invalid"
    return style_name


def _project_tag_style_name(
    role: XPromptHighlightRole,
    accent: str | None,
) -> str:
    """Return the registered TextArea style for a project-tag span (D6)."""
    if role == "xprompt.project_tag.unknown":
        return "project_tag.unknown"
    base = (
        "project_tag.sigil"
        if role == "xprompt.project_tag.sigil"
        else "project_tag.name"
    )
    if accent is None:
        return f"{base}.neutral"
    try:
        return f"{base}.{PROJECT_ACCENTS.index(accent)}"
    except ValueError:
        return f"{base}.neutral"


def _argument_style_name(
    role: XPromptHighlightRole,
    source: XPromptArgumentSource | None,
) -> str:
    if role in _ARGUMENT_ROLES and source == "directive":
        return f"xprompt.directive.{role.removeprefix('xprompt.')}"
    return role


def _update_argument_syntax_styles(
    syntax_styles: dict[str, Style],
    colors: Mapping[XPromptHighlightRole, str | None],
    *,
    source: XPromptArgumentSource,
) -> None:
    for role, color in colors.items():
        style_name = _argument_style_name(role, source)
        syntax_styles[style_name] = Style(color=color)
        syntax_styles[f"{style_name}.invalid"] = Style(color=color, underline=True)


def _update_project_tag_syntax_styles(
    syntax_styles: dict[str, Style],
    warning: str | None,
) -> None:
    """Register per-accent project-tag styles (D6).

    ``project_tag.sigil.<0-17>`` renders ``dim`` in the accent and
    ``project_tag.name.<0-17>`` renders ``bold`` in the accent, matching
    the top-right project chip. The ``.neutral`` styles cover disabled
    projects and ``home``; ``project_tag.unknown`` covers anchored
    unknown tags in the theme warning color with an underline.
    """
    for index, accent in enumerate(PROJECT_ACCENTS):
        syntax_styles[f"project_tag.sigil.{index}"] = Style(color=accent, dim=True)
        syntax_styles[f"project_tag.name.{index}"] = Style(color=accent, bold=True)
    syntax_styles["project_tag.sigil.neutral"] = Style(dim=True)
    syntax_styles["project_tag.name.neutral"] = Style(dim=True)
    syntax_styles["project_tag.unknown"] = Style(color=warning, underline=True)
