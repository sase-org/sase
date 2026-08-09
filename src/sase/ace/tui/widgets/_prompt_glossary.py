"""Project glossary highlighting, preview, and jump support for prompts."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.style import Style
from textual.widgets._text_area import TextAreaTheme

from sase.ace.tui.glossary_catalog import PromptGlossaryContext
from sase.ace.tui.widgets._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from sase.core.glossary_facade import (
    GlossaryEntry,
    GlossarySpan,
    lookup_glossary_span,
    scan_glossary_spans,
)
from sase.xprompt.highlight_theme import derive_argument_color

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase

    from sase.xprompt.glossary_catalog import EditorGlossaryCatalog
else:
    _MixinBase = object


_GLOSSARY_STYLE = "glossary.term"


class PromptGlossaryMixin(_MixinBase):
    """Memory-only glossary overlay and actions for ``PromptTextArea``.

    The render path uses the last resolved prompt context and scans the current
    buffer text against that already-warm catalog. Context computation and
    catalog warming stay outside highlight rebuilds so typing never performs
    project resolution or schedules work.

    The glossary term style is the definable-term link affordance: bold,
    theme-accent text with an additive underline. Later structural overlays
    keep winning on overlap, and clear that underline when their surface must
    suppress inherited text attributes.
    """

    if TYPE_CHECKING:
        _prompt_glossary_context_cache: PromptGlossaryContext | None
        _prompt_glossary_scan_catalog: object | None
        _prompt_glossary_scan_text: str | None
        _prompt_glossary_cached_spans: tuple[GlossarySpan, ...] | None

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _append_highlight_span(
            self,
            start: int,
            end: int,
            style_name: str,
        ) -> None: ...
        def _preview_context(self) -> tuple[str | None, str]: ...
        def _present_jump_actions(self, payload: Any) -> None: ...
        def _xprompt_arg_assist_project_from_text(self) -> str | None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._prompt_glossary_context_cache: PromptGlossaryContext | None = None
        self._prompt_glossary_scan_catalog: object | None = None
        self._prompt_glossary_scan_text: str | None = None
        self._prompt_glossary_cached_spans: tuple[GlossarySpan, ...] | None = None
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        """Register glossary styles and schedule the first prompt context."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._register_glossary_text_area_theme()
        self._refresh_prompt_glossary_context(schedule=True)

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        self._register_glossary_text_area_theme()

    def _register_jinja_text_area_theme(self) -> None:
        register_jinja = getattr(super(), "_register_jinja_text_area_theme", None)
        if callable(register_jinja):
            register_jinja()
        self._register_glossary_text_area_theme(_JINJA_THEME_NAME, apply=False)

    def _on_prompt_completion_context_changed(self) -> None:
        super_changed = getattr(super(), "_on_prompt_completion_context_changed", None)
        if callable(super_changed):
            super_changed()
        self._refresh_prompt_glossary_context(schedule=True)

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        text = self.text
        if not text.strip():
            return
        if len(text.encode("utf-8")) > _MAX_OVERLAY_BYTES:
            return
        if text.count("\n") > _MAX_OVERLAY_LINES:
            return

        catalog = self._warm_prompt_glossary_catalog_for_render()
        if catalog is None:
            return
        try:
            spans = self._prompt_glossary_spans_for_render(catalog, text)
        except Exception:
            return
        for span in spans:
            offsets = _editor_range_to_offsets(text, span.range)
            if offsets is None:
                continue
            self._append_highlight_span(*offsets, _GLOSSARY_STYLE)

    def _preview_glossary_under_cursor(self) -> bool:
        """Preview the glossary term under the cursor, if one is selected."""
        match = self._glossary_match_under_cursor(schedule=True)
        if isinstance(match, _ColdGlossaryCatalogType):
            self.notify(
                "Glossary catalog is still loading; try again",
                severity="warning",
            )
            return True
        if match is None:
            return False
        catalog, span, entry = match

        from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
        from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload

        payload = PreviewPayload(
            kind_label="glossary",
            icon="G",
            title=entry.term,
            source_path=_glossary_source_path(catalog, entry),
            content=_glossary_preview_markdown(catalog, entry),
            lexer="markdown",
            reference=span.matched_text,
            default_view="rendered",
        )
        self.app.push_screen(PreviewPanelModal(payload))
        return True

    def _jump_to_glossary_definition_under_cursor(self) -> bool:
        """Jump to the source definition for the glossary term under cursor."""
        match = self._glossary_match_under_cursor(schedule=True)
        if isinstance(match, _ColdGlossaryCatalogType):
            self.notify(
                "Glossary catalog is still loading; try again",
                severity="warning",
            )
            return True
        if match is None:
            return False
        catalog, _span, entry = match

        from sase.ace.tui.widgets._prompt_jump_target import JumpTarget

        source_path = _glossary_source_path(catalog, entry)
        line, col = _glossary_definition_position(entry)
        payload = JumpTarget(
            kind_label="glossary",
            icon="G",
            title=entry.term,
            source_path=source_path or str(catalog.config_path),
            line=line,
            col=col,
            loadable_markdown=None,
            definition_name=entry.term,
            source_id=source_path,
            is_editable=True,
        )
        self._present_jump_actions(payload)
        return True

    def _warm_prompt_glossary_catalog_for_render(
        self,
    ) -> EditorGlossaryCatalog | None:
        """Return the catalog for the last resolved context without scheduling work."""
        context = self._prompt_glossary_context_cache
        if context is None:
            return None
        return self._get_prompt_glossary_catalog(context, schedule=False)

    def _refresh_prompt_glossary_context(self, *, schedule: bool) -> None:
        previous = self._prompt_glossary_context_cache
        context = self._compute_prompt_glossary_context()
        self._prompt_glossary_context_cache = context
        if schedule:
            self._schedule_prompt_glossary_warm(context)
        if context != previous and self._active_app() is not None:
            self._build_highlight_map()
            self.refresh()

    def _prompt_glossary_spans_for_render(
        self,
        catalog: EditorGlossaryCatalog,
        text: str,
    ) -> tuple[GlossarySpan, ...]:
        compiled = catalog.compiled
        if (
            self._prompt_glossary_scan_catalog is compiled
            and self._prompt_glossary_scan_text == text
            and self._prompt_glossary_cached_spans is not None
        ):
            return self._prompt_glossary_cached_spans

        spans = scan_glossary_spans(compiled, text)
        self._prompt_glossary_scan_catalog = compiled
        self._prompt_glossary_scan_text = text
        self._prompt_glossary_cached_spans = spans
        return spans

    def _compute_prompt_glossary_context(self) -> PromptGlossaryContext:
        project_ref: str | None = None
        try:
            project_ref = self._xprompt_arg_assist_project_from_text()
        except Exception:
            project_ref = None

        launch_workspace: str | None = None
        app = self._active_app()
        if app is not None:
            ctx = getattr(app, "_prompt_context", None)
            if ctx is not None and not bool(getattr(ctx, "is_home_mode", False)):
                workspace_dir = getattr(ctx, "workspace_dir", None)
                if isinstance(workspace_dir, str) and workspace_dir:
                    launch_workspace = workspace_dir

        if project_ref is None:
            try:
                _project, base_dir = self._preview_context()
            except Exception:
                base_dir = ""
            if base_dir and base_dir != str(Path.home()):
                launch_workspace = launch_workspace or base_dir

        return PromptGlossaryContext(
            project_ref=project_ref,
            launch_workspace=launch_workspace,
        )

    def _glossary_match_under_cursor(
        self,
        *,
        schedule: bool,
    ) -> (
        tuple[EditorGlossaryCatalog, GlossarySpan, GlossaryEntry]
        | _ColdGlossaryCatalogType
        | None
    ):
        self._refresh_prompt_glossary_context(schedule=False)
        context = self._prompt_glossary_context_cache
        if context is None:
            return None
        catalog = self._get_prompt_glossary_catalog(context, schedule=False)
        if catalog is None:
            if not self._is_prompt_glossary_catalog_warm(context):
                if schedule:
                    self._schedule_prompt_glossary_warm(context)
                return _ColdGlossaryCatalog
            return None

        row, col = self.cursor_location
        line = (
            self.document.get_line(row) if 0 <= row < self.document.line_count else ""
        )
        character = _utf16_character(line[: max(0, min(col, len(line)))])
        try:
            span = lookup_glossary_span(
                catalog.compiled,
                self.text,
                line=row,
                character=character,
            )
        except Exception:
            return None
        if span is None:
            return None
        entry = _entry_for_span(catalog, span)
        if entry is None:
            return None
        return catalog, span, entry

    def _get_prompt_glossary_catalog(
        self,
        context: PromptGlossaryContext,
        *,
        schedule: bool,
    ) -> EditorGlossaryCatalog | None:
        app = self._active_app()
        if app is None:
            return None
        getter = getattr(app, "get_prompt_glossary_catalog", None)
        if not callable(getter):
            return None
        value = getter(context, schedule=schedule)
        return value

    def _is_prompt_glossary_catalog_warm(
        self,
        context: PromptGlossaryContext,
    ) -> bool:
        app = self._active_app()
        if app is None:
            return True
        checker = getattr(app, "is_prompt_glossary_catalog_warm", None)
        if not callable(checker):
            return True
        try:
            return bool(checker(context))
        except Exception:
            return True

    def _schedule_prompt_glossary_warm(
        self,
        context: PromptGlossaryContext,
    ) -> None:
        app = self._active_app()
        if app is None:
            return
        warmer = getattr(app, "warm_prompt_glossary_catalog", None)
        if callable(warmer):
            warmer(context)

    def _active_app(self) -> Any | None:
        try:
            return self.app
        except Exception:
            return None

    def _register_glossary_text_area_theme(
        self,
        theme_name: str | None = None,
        *,
        apply: bool = True,
    ) -> None:
        active_name = theme_name or str(getattr(self, "theme", "css") or "css")
        base = self._resolve_glossary_base_theme(active_name)
        syntax_styles = dict(base.syntax_styles)
        app_theme = self.app.current_theme
        background = app_theme.background or "#000000"
        syntax_styles[_GLOSSARY_STYLE] = Style(
            color=derive_argument_color(
                app_theme.primary,
                foreground=app_theme.foreground,
                background=background,
            ),
            bold=True,
            underline=True,
        )
        theme = dataclasses.replace(
            base,
            name=active_name,
            syntax_styles=syntax_styles,
        )
        self.register_theme(theme)
        if apply:
            self._set_theme(theme.name)

    def _resolve_glossary_base_theme(self, theme_name: str) -> TextAreaTheme:
        try:
            theme: TextAreaTheme | None = self._themes[theme_name]
        except KeyError:
            theme = TextAreaTheme.get_builtin_theme(theme_name)
        if theme is None:
            fallback = TextAreaTheme.get_builtin_theme("css")
            assert fallback is not None
            return fallback
        return theme


class _ColdGlossaryCatalogType:
    pass


_ColdGlossaryCatalog = _ColdGlossaryCatalogType()


def _entry_for_span(
    catalog: EditorGlossaryCatalog,
    span: GlossarySpan,
) -> GlossaryEntry | None:
    for entry in catalog.catalog.entries:
        if entry.index == span.entry_index:
            return entry
    return None


def _glossary_preview_markdown(
    catalog: EditorGlossaryCatalog,
    entry: GlossaryEntry,
) -> str:
    lines = [
        f"# {entry.term}",
        "",
        entry.definition.strip(),
    ]
    aliases = tuple(alias for alias in entry.configured_aliases if alias)
    if aliases:
        lines.extend(("", f"ALIASES: {', '.join(aliases)}"))
    project = getattr(catalog.project, "name", None) or getattr(
        catalog.project, "key", ""
    )
    if project:
        lines.extend(("", f"PROJECT: {project}"))
    source = _glossary_source_display(catalog, entry)
    if source:
        lines.extend(("", f"SOURCE: `{source}`"))
    return "\n".join(lines).rstrip() + "\n"


def _glossary_source_display(
    catalog: EditorGlossaryCatalog,
    entry: GlossaryEntry,
) -> str | None:
    path = _glossary_source_path(catalog, entry)
    if path is None:
        return None
    line, col = _glossary_definition_position(entry)
    if line is None:
        return path
    if col is None:
        return f"{path}:{line}"
    return f"{path}:{line}:{col}"


def _glossary_source_path(
    catalog: EditorGlossaryCatalog,
    entry: GlossaryEntry,
) -> str | None:
    source = entry.source if isinstance(entry.source, dict) else None
    path = source.get("config_path") if source is not None else None
    if isinstance(path, str) and path:
        return path
    config_path = getattr(catalog, "config_path", None)
    return str(config_path) if config_path is not None else None


def _glossary_definition_position(
    entry: GlossaryEntry,
) -> tuple[int | None, int | None]:
    source = entry.source if isinstance(entry.source, dict) else None
    definition_range = source.get("definition_range") if source is not None else None
    if not isinstance(definition_range, dict):
        return None, None
    start = definition_range.get("start")
    if not isinstance(start, dict):
        return None, None
    line = start.get("line")
    character = start.get("character")
    out_line = int(line) + 1 if isinstance(line, int) and line >= 0 else None
    out_col = (
        int(character) + 1 if isinstance(character, int) and character >= 0 else None
    )
    return out_line, out_col


def _editor_range_to_offsets(
    text: str,
    editor_range: Any,
) -> tuple[int, int] | None:
    if not isinstance(editor_range, dict):
        return None
    start = _editor_position_to_offset(text, editor_range.get("start"))
    end = _editor_position_to_offset(text, editor_range.get("end"))
    if start is None or end is None or end <= start:
        return None
    return start, end


def _editor_position_to_offset(text: str, position: Any) -> int | None:
    if not isinstance(position, dict):
        return None
    line = position.get("line")
    character = position.get("character")
    if not isinstance(line, int) or not isinstance(character, int):
        return None
    if line < 0 or character < 0:
        return None

    row = 0
    line_start = 0
    while row < line:
        newline = text.find("\n", line_start)
        if newline == -1:
            return None
        line_start = newline + 1
        row += 1

    line_end = text.find("\n", line_start)
    if line_end == -1:
        line_end = len(text)
    column = _python_column_from_utf16(text[line_start:line_end], character)
    if column is None:
        return None
    return line_start + column


def _python_column_from_utf16(line: str, character: int) -> int | None:
    remaining = character
    for index, char in enumerate(line):
        width = 2 if ord(char) > 0xFFFF else 1
        if remaining == 0:
            return index
        if remaining < width:
            return index
        remaining -= width
    return len(line) if remaining == 0 else None


def _utf16_character(text: str) -> int:
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)


__all__ = [
    "PromptGlossaryMixin",
]
