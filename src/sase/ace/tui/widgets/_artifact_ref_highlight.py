"""Artifact-reference syntax highlighting for ``PromptTextArea``."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.widgets._text_area import TextAreaTheme
from textual.worker import Worker, WorkerState

from sase.ace.tui.util.artifact_ref_syntax import (
    artifact_ref_style_palette_from_theme,
    artifact_ref_styled_spans,
    build_artifact_ref_candidate_spans,
)
from sase.artifact_refs import (
    ArtifactRefContext,
    artifact_ref_context,
    parsable_artifact_ref_kinds,
)
from sase.xprompt.project_identity import known_project_namespaces

from ._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from .artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
    ArtifactRefCompletionCatalog,
    load_artifact_ref_completion_catalog,
)

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


_ARTIFACT_REF_WORKER_GROUP = "prompt-artifact-ref-kinds"


@dataclass(frozen=True, slots=True)
class _KnownKindsResult:
    project: str | None
    kinds: frozenset[str]
    catalog: ArtifactRefCompletionCatalog | None = None
    context: ArtifactRefContext | None = None
    generation: int = 0


def resolve_artifact_ref_warm_workspace(
    project: str | None,
    workspace_dir: str | None,
    workspace_num: int,
) -> tuple[Path, int]:
    """Resolve the workspace backing one target project's warm ref state.

    A target-project namespace wins over the caller's session workspace because
    the resulting catalog is cached by target project. The caller workspace is
    the fallback, followed by the current directory. Shared by the completion
    catalog warm path and the ``@<kind>::`` sync gesture so both read/write the
    same on-disk clone.
    """
    project_workspace = (
        known_project_namespaces().get(project) if project is not None else None
    )
    if project_workspace is not None:
        return project_workspace, 1
    if workspace_dir:
        return Path(workspace_dir), workspace_num if workspace_num > 0 else 1
    return Path.cwd(), 1


def _load_known_artifact_ref_kinds(
    project: str | None,
    workspace_dir: str | None,
    workspace_num: int,
    generation: int = 0,
) -> _KnownKindsResult:
    """Load known kinds from the workspace represented by the cache key."""
    workspace, effective_workspace_num = resolve_artifact_ref_warm_workspace(
        project,
        workspace_dir,
        workspace_num,
    )

    try:
        context = artifact_ref_context(
            workspace,
            effective_workspace_num,
            project=project,
        )
    except Exception:
        kinds = frozenset(parsable_artifact_ref_kinds())
        return _KnownKindsResult(
            project,
            kinds,
            ArtifactRefCompletionCatalog(project, tuple(parsable_artifact_ref_kinds())),
            generation=generation,
        )
    return _KnownKindsResult(
        project,
        frozenset(context.known_kinds),
        load_artifact_ref_completion_catalog(project, context),
        context,
        generation,
    )


class ArtifactRefHighlightMixin(_MixinBase):
    """Overlay known artifact references without doing I/O while typing."""

    if TYPE_CHECKING:
        _artifact_ref_known_kinds_by_project: dict[str | None, frozenset[str]]
        _artifact_ref_completion_catalogs_by_project: dict[
            str | None, ArtifactRefCompletionCatalog
        ]
        _artifact_ref_kind_worker_projects: dict[str, str | None]
        _artifact_ref_kinds_warming: set[str | None]
        _artifact_ref_contexts_by_project: dict[str | None, ArtifactRefContext]
        _artifact_ref_catalog_generation: int

        def _append_highlight_span(
            self,
            start: int,
            end: int,
            style_name: str,
        ) -> None: ...

        def _xprompt_arg_assist_project_from_text(self) -> str | None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # TextArea builds its first highlight map inside its constructor, so
        # this cache must exist before delegating to the base widget.
        self._artifact_ref_known_kinds_by_project = {}
        self._artifact_ref_completion_catalogs_by_project = {}
        self._artifact_ref_contexts_by_project = {}
        self._artifact_ref_kinds_warming = set()
        self._artifact_ref_kind_worker_projects = {}
        self._artifact_ref_catalog_generation = 0
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        """Register artifact-reference styles after the base theme exists."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._register_artifact_ref_text_area_theme()

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        self._register_artifact_ref_text_area_theme()

    def _register_jinja_text_area_theme(self) -> None:
        register_jinja = getattr(super(), "_register_jinja_text_area_theme", None)
        if callable(register_jinja):
            register_jinja()
        self._register_artifact_ref_text_area_theme(
            _JINJA_THEME_NAME,
            apply=False,
        )

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        text = self.text
        if "@" not in text:
            return
        known_kinds = self._get_warm_artifact_ref_known_kinds()
        candidates = build_artifact_ref_candidate_spans(
            text,
            known_kinds=known_kinds,
            max_bytes=_MAX_OVERLAY_BYTES,
            max_lines=_MAX_OVERLAY_LINES,
        )
        for span in artifact_ref_styled_spans(candidates):
            self._append_highlight_span(
                span.span.start,
                span.span.end,
                span.style_name,
            )

    def _append_artifact_ref_span(
        self,
        span: Any,
        style_name: str,
    ) -> None:
        """Compatibility wrapper for older focused widget tests."""
        self._append_highlight_span(span.start, span.end, style_name)

    def _get_warm_artifact_ref_known_kinds(self) -> frozenset[str] | None:
        """Return the current project's memory-only known-kind set."""
        try:
            project = self._xprompt_arg_assist_project_from_text()
        except Exception:
            project = None
        return self._artifact_ref_known_kinds_by_project.get(project)

    def _get_warm_artifact_ref_completion_catalog(
        self,
    ) -> ArtifactRefCompletionCatalog | None:
        """Return the current target project's immutable warm payload catalog."""
        try:
            project = self._xprompt_arg_assist_project_from_text()
        except Exception:
            project = None
        return self._artifact_ref_completion_catalogs_by_project.get(project)

    def _get_warm_artifact_ref_context(self) -> ArtifactRefContext | None:
        """Return the current target project's already-built local context."""
        try:
            project = self._xprompt_arg_assist_project_from_text()
        except Exception:
            project = None
        return self._artifact_ref_contexts_by_project.get(project)

    def _warm_current_artifact_ref_known_kinds(self) -> None:
        """Warm project kinds and payloads for disk-free prompt interaction."""
        if not callable(getattr(self.app, "get_prompt_completion_settings", None)):
            return
        project = self._xprompt_arg_assist_project_from_text()
        if (
            project in self._artifact_ref_completion_catalogs_by_project
            or project in self._artifact_ref_kinds_warming
        ):
            return

        workspace_dir: str | None = None
        workspace_num = 1
        context = getattr(self.app, "_prompt_context", None)
        if context is not None:
            raw_workspace_dir = getattr(context, "workspace_dir", None)
            if isinstance(raw_workspace_dir, str) and raw_workspace_dir:
                workspace_dir = raw_workspace_dir
            raw_workspace_num = getattr(context, "workspace_num", None)
            if isinstance(raw_workspace_num, int) and raw_workspace_num > 0:
                workspace_num = raw_workspace_num

        worker_name = (
            f"{_ARTIFACT_REF_WORKER_GROUP}:"
            f"{len(self._artifact_ref_kind_worker_projects)}"
        )
        self._artifact_ref_kinds_warming.add(project)
        self._artifact_ref_kind_worker_projects[worker_name] = project
        generation = self._artifact_ref_catalog_generation
        self.run_worker(
            lambda: dataclasses.replace(
                _load_known_artifact_ref_kinds(
                    project,
                    workspace_dir,
                    workspace_num,
                ),
                generation=generation,
            ),
            name=worker_name,
            group=_ARTIFACT_REF_WORKER_GROUP,
            thread=True,
        )

    def _warm_current_artifact_ref_completion_catalog(self) -> None:
        """Warm the catalog through the highlighter's shared lifecycle."""
        self._warm_current_artifact_ref_known_kinds()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Apply warmed role sets and preserve other prompt worker handlers."""
        if event.worker.group != _ARTIFACT_REF_WORKER_GROUP:
            handler = getattr(super(), "on_worker_state_changed", None)
            if callable(handler):
                handler(event)
            return

        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if isinstance(result, _KnownKindsResult):
                if result.generation != self._artifact_ref_catalog_generation:
                    self._artifact_ref_kinds_warming.discard(result.project)
                    self._artifact_ref_kind_worker_projects.pop(
                        event.worker.name,
                        None,
                    )
                    return
                self._artifact_ref_known_kinds_by_project[result.project] = result.kinds
                if result.catalog is not None:
                    self._artifact_ref_completion_catalogs_by_project[
                        result.project
                    ] = result.catalog
                if result.context is not None:
                    self._artifact_ref_contexts_by_project[result.project] = (
                        result.context
                    )
                self._artifact_ref_kinds_warming.discard(result.project)
                self._artifact_ref_kind_worker_projects.pop(event.worker.name, None)
                self._build_highlight_map()
                self.refresh()
                if (
                    result.catalog is not None
                    and getattr(self, "_file_completion_active", False)
                    and getattr(self, "_completion_kind", "")
                    == ARTIFACT_REF_COMPLETION_KIND
                    and self._xprompt_arg_assist_project_from_text() == result.project
                ):
                    refresh_completion = getattr(
                        self,
                        "_refresh_file_completion_from_cursor",
                        None,
                    )
                    if callable(refresh_completion):
                        refresh_completion()
                finish_sync_reload = getattr(
                    self,
                    "_finish_artifact_ref_sync_reload_for_project",
                    None,
                )
                if callable(finish_sync_reload):
                    finish_sync_reload(result.project)
                return
        elif event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
            project = self._artifact_ref_kind_worker_projects.pop(
                event.worker.name,
                None,
            )
            self._artifact_ref_kinds_warming.discard(project)

        handler = getattr(super(), "on_worker_state_changed", None)
        if callable(handler):
            handler(event)

    def invalidate_artifact_ref_completion_cache(self) -> None:
        """Drop warm ref catalogs after xprompt/ref source configuration changes."""
        self._artifact_ref_catalog_generation += 1
        self._artifact_ref_known_kinds_by_project.clear()
        self._artifact_ref_completion_catalogs_by_project.clear()
        self._artifact_ref_contexts_by_project.clear()
        self._artifact_ref_kinds_warming.clear()
        self._artifact_ref_kind_worker_projects.clear()
        if getattr(self, "_completion_kind", "") == ARTIFACT_REF_COMPLETION_KIND:
            self._warm_current_artifact_ref_completion_catalog()
        self._build_highlight_map()
        self.refresh()

    def _register_artifact_ref_text_area_theme(
        self,
        theme_name: str | None = None,
        *,
        apply: bool = True,
    ) -> None:
        active_name = theme_name or str(getattr(self, "theme", "css") or "css")
        base = self._resolve_artifact_ref_base_theme(active_name)
        syntax_styles = dict(base.syntax_styles)
        palette = artifact_ref_style_palette_from_theme(self.app.current_theme)
        syntax_styles.update(palette.styles)
        theme = dataclasses.replace(
            base,
            name=active_name,
            syntax_styles=syntax_styles,
        )
        self.register_theme(theme)
        if apply:
            self._set_theme(theme.name)

    def _resolve_artifact_ref_base_theme(self, theme_name: str) -> TextAreaTheme:
        try:
            theme: TextAreaTheme | None = self._themes[theme_name]
        except KeyError:
            theme = TextAreaTheme.get_builtin_theme(theme_name)
        if theme is None:
            fallback = TextAreaTheme.get_builtin_theme("css")
            assert fallback is not None
            return fallback
        return theme


__all__ = ["ArtifactRefHighlightMixin"]
