"""Project repo-mention highlighting and cursor lookup for prompts."""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.widgets._text_area import TextAreaTheme

from sase.ace.tui.modals.repo_preview_render import repo_checkout_path
from sase.ace.tui.repo_mention_catalog import PromptRepoMentionContext
from sase.ace.tui.util.editor_offsets import (
    editor_range_to_offsets as _editor_range_to_offsets,
    utf16_character as _utf16_character,
)
from sase.ace.tui.util.semantic_styles import semantic_highlight_styles_from_theme
from sase.ace.tui.widgets._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from sase.xprompt.repo_mention_catalog import (
    EditorRepoMentionCatalog,
    RepoMentionSpan,
    lookup_repo_mention,
    scan_repo_mentions,
)

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


_REPO_MENTION_STYLE = "repo.mention"


class PromptRepoMentionMixin(_MixinBase):
    """Memory-only repo-mention overlay for ``PromptTextArea``.

    The render path uses the last resolved prompt context and scans the current
    buffer text against that already-warm catalog. Context computation and
    catalog warming stay outside highlight rebuilds so typing never performs
    project resolution or schedules work.

    The repo-mention style is the same definable-thing link affordance as
    glossary terms — bold plus underline — in the theme-accent lavender so
    the two read as siblings.
    """

    if TYPE_CHECKING:
        _prompt_repo_mention_context_cache: PromptRepoMentionContext | None
        _prompt_repo_mention_scan_catalog: object | None
        _prompt_repo_mention_scan_text: str | None
        _prompt_repo_mention_cached_spans: tuple[RepoMentionSpan, ...] | None

        def _append_highlight_span(
            self,
            start: int,
            end: int,
            style_name: str,
        ) -> None: ...
        def _preview_context(self) -> tuple[str | None, str]: ...
        def _present_jump_actions(self, payload: Any) -> None: ...
        def _perform_jump_action(self, choice: Any, payload: Any) -> None: ...
        def _xprompt_arg_assist_project_from_text(self) -> str | None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._prompt_repo_mention_context_cache: PromptRepoMentionContext | None = None
        self._prompt_repo_mention_scan_catalog: object | None = None
        self._prompt_repo_mention_scan_text: str | None = None
        self._prompt_repo_mention_cached_spans: tuple[RepoMentionSpan, ...] | None = (
            None
        )
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        """Register repo-mention styles and schedule the first prompt context."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._register_repo_mention_text_area_theme()
        self._refresh_prompt_repo_mention_context(schedule=True)

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        self._register_repo_mention_text_area_theme()

    def _register_jinja_text_area_theme(self) -> None:
        register_jinja = getattr(super(), "_register_jinja_text_area_theme", None)
        if callable(register_jinja):
            register_jinja()
        self._register_repo_mention_text_area_theme(_JINJA_THEME_NAME, apply=False)

    def _on_prompt_completion_context_changed(self) -> None:
        super_changed = getattr(super(), "_on_prompt_completion_context_changed", None)
        if callable(super_changed):
            super_changed()
        self._refresh_prompt_repo_mention_context(schedule=True)

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        text = self.text
        if not text.strip():
            return
        if len(text.encode("utf-8")) > _MAX_OVERLAY_BYTES:
            return
        if text.count("\n") > _MAX_OVERLAY_LINES:
            return

        catalog = self._warm_prompt_repo_mention_catalog_for_render()
        if catalog is None:
            return
        try:
            spans = self._prompt_repo_mention_spans_for_render(catalog, text)
        except Exception:
            return
        for span in spans:
            for segment in span.segments:
                if not isinstance(segment, Mapping):
                    continue
                offsets = _editor_range_to_offsets(text, segment.get("range"))
                if offsets is None:
                    continue
                self._append_highlight_span(*offsets, _REPO_MENTION_STYLE)

    def _warm_prompt_repo_mention_catalog_for_render(
        self,
    ) -> EditorRepoMentionCatalog | None:
        """Return the catalog for the last resolved context without scheduling work."""
        context = self._prompt_repo_mention_context_cache
        if context is None:
            return None
        return self._get_prompt_repo_mention_catalog(context, schedule=False)

    def _refresh_prompt_repo_mention_context(self, *, schedule: bool) -> None:
        previous = self._prompt_repo_mention_context_cache
        context = self._compute_prompt_repo_mention_context()
        self._prompt_repo_mention_context_cache = context
        if schedule:
            self._schedule_prompt_repo_mention_warm(context)
        if context != previous and self._active_app() is not None:
            self._build_highlight_map()
            self.refresh()

    def _prompt_repo_mention_spans_for_render(
        self,
        catalog: EditorRepoMentionCatalog,
        text: str,
    ) -> tuple[RepoMentionSpan, ...]:
        compiled = catalog.compiled
        if (
            self._prompt_repo_mention_scan_catalog is compiled
            and self._prompt_repo_mention_scan_text == text
            and self._prompt_repo_mention_cached_spans is not None
        ):
            return self._prompt_repo_mention_cached_spans

        spans = scan_repo_mentions(catalog, text)
        self._prompt_repo_mention_scan_catalog = compiled
        self._prompt_repo_mention_scan_text = text
        self._prompt_repo_mention_cached_spans = spans
        return spans

    def _compute_prompt_repo_mention_context(self) -> PromptRepoMentionContext:
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

        return PromptRepoMentionContext(
            project_ref=project_ref,
            launch_workspace=launch_workspace,
        )

    def _preview_repo_mention_under_cursor(self) -> bool:
        """Preview the repo mention under the cursor, if one is selected."""
        match = self._repo_mention_under_cursor(schedule=True)
        if isinstance(match, _ColdRepoCatalogType):
            self.notify(
                "Repo catalog is still loading; try again",
                severity="warning",
            )
            return True
        if match is None:
            return False
        catalog, span = match

        from sase.ace.tui.modals.repo_preview_modal import RepoPreviewModal

        self.app.push_screen(
            RepoPreviewModal(catalog, span.mention, matched_text=span.matched_text)
        )
        return True

    def _jump_to_repo_mention_under_cursor(self) -> bool:
        """Open the checkout for the repo mention under the cursor, if any."""
        match = self._repo_mention_under_cursor(schedule=True)
        if isinstance(match, _ColdRepoCatalogType):
            self.notify(
                "Repo catalog is still loading; try again",
                severity="warning",
            )
            return True
        if match is None:
            return False
        _catalog, span = match
        mention = span.mention

        from sase.ace.tui.widgets._prompt_jump_target import JumpTarget

        workspace_num = _active_workspace_num(self._active_app())
        path, exists = repo_checkout_path(mention, workspace_num=workspace_num)
        payload = JumpTarget(
            kind_label="repo",
            icon="R",
            title=mention.identifier,
            source_path=path,
            line=None,
            col=None,
            loadable_markdown=None,
            is_editable=False,
            config_path=mention.config_path,
            config_line=mention.config_line,
            config_col=mention.config_col,
        )

        if not exists:
            self.notify(
                f"{mention.identifier} is not cloned in this workspace; "
                f"run `sase repo open {mention.identifier}`",
                severity="warning",
            )
            if payload.config_path is not None:
                self._perform_jump_action("config", payload)
            return True

        self._present_jump_actions(payload)
        return True

    def _repo_mention_under_cursor(
        self,
        *,
        schedule: bool,
    ) -> tuple[EditorRepoMentionCatalog, RepoMentionSpan] | _ColdRepoCatalogType | None:
        self._refresh_prompt_repo_mention_context(schedule=False)
        context = self._prompt_repo_mention_context_cache
        if context is None:
            return None
        catalog = self._get_prompt_repo_mention_catalog(context, schedule=False)
        if catalog is None:
            if not self._is_prompt_repo_mention_catalog_warm(context):
                if schedule:
                    self._schedule_prompt_repo_mention_warm(context)
                return _ColdRepoCatalog
            return None

        row, col = self.cursor_location
        line = (
            self.document.get_line(row) if 0 <= row < self.document.line_count else ""
        )
        character = _utf16_character(line[: max(0, min(col, len(line)))])
        try:
            span = lookup_repo_mention(
                catalog,
                self.text,
                line=row,
                character=character,
            )
        except Exception:
            return None
        if span is None:
            return None
        return catalog, span

    def _get_prompt_repo_mention_catalog(
        self,
        context: PromptRepoMentionContext,
        *,
        schedule: bool,
    ) -> EditorRepoMentionCatalog | None:
        app = self._active_app()
        if app is None:
            return None
        getter = getattr(app, "get_prompt_repo_mention_catalog", None)
        if not callable(getter):
            return None
        value = getter(context, schedule=schedule)
        return value

    def _is_prompt_repo_mention_catalog_warm(
        self,
        context: PromptRepoMentionContext,
    ) -> bool:
        app = self._active_app()
        if app is None:
            return True
        checker = getattr(app, "is_prompt_repo_mention_catalog_warm", None)
        if not callable(checker):
            return True
        try:
            return bool(checker(context))
        except Exception:
            return True

    def _schedule_prompt_repo_mention_warm(
        self,
        context: PromptRepoMentionContext,
    ) -> None:
        app = self._active_app()
        if app is None:
            return
        warmer = getattr(app, "warm_prompt_repo_mention_catalog", None)
        if callable(warmer):
            warmer(context)

    def _active_app(self) -> Any | None:
        try:
            return self.app
        except Exception:
            return None

    def _register_repo_mention_text_area_theme(
        self,
        theme_name: str | None = None,
        *,
        apply: bool = True,
    ) -> None:
        active_name = theme_name or str(getattr(self, "theme", "css") or "css")
        base = self._resolve_repo_mention_base_theme(active_name)
        syntax_styles = dict(base.syntax_styles)
        styles = semantic_highlight_styles_from_theme(self.app.current_theme)
        if styles is not None:
            syntax_styles[_REPO_MENTION_STYLE] = styles.repo
        theme = dataclasses.replace(
            base,
            name=active_name,
            syntax_styles=syntax_styles,
        )
        self.register_theme(theme)
        if apply:
            self._set_theme(theme.name)

    def _resolve_repo_mention_base_theme(self, theme_name: str) -> TextAreaTheme:
        try:
            theme: TextAreaTheme | None = self._themes[theme_name]
        except KeyError:
            theme = TextAreaTheme.get_builtin_theme(theme_name)
        if theme is None:
            fallback = TextAreaTheme.get_builtin_theme("css")
            assert fallback is not None
            return fallback
        return theme


class _ColdRepoCatalogType:
    pass


_ColdRepoCatalog = _ColdRepoCatalogType()


def _active_workspace_num(app: Any) -> int | None:
    if app is None:
        return None
    ctx = getattr(app, "_prompt_context", None)
    if ctx is None or bool(getattr(ctx, "is_home_mode", False)):
        return None
    workspace_num = getattr(ctx, "workspace_num", None)
    return workspace_num if isinstance(workspace_num, int) else None


__all__ = [
    "PromptRepoMentionMixin",
]
