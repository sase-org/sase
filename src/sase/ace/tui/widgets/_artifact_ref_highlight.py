"""Artifact-reference syntax highlighting for ``PromptTextArea``."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.style import Style
from textual.widgets._text_area import TextAreaTheme
from textual.worker import Worker, WorkerState

from sase.artifact_refs import (
    BUILTIN_ARTIFACT_REF_KINDS,
    ArtifactRefPromptCandidate,
    ArtifactRefSpan,
    artifact_ref_context,
    scan_artifact_refs,
)
from sase.xprompt._literal_zones import literal_zone_ranges
from sase.xprompt.project_identity import known_project_namespaces

from ._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from ._xprompt_syntax_highlight import derive_argument_color

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


_ARTIFACT_REF_WORKER_GROUP = "prompt-artifact-ref-kinds"


@dataclass(frozen=True, slots=True)
class _KnownKindsResult:
    project: str | None
    kinds: frozenset[str]


def _load_known_artifact_ref_kinds(
    project: str | None,
    workspace_dir: str | None,
    workspace_num: int,
) -> _KnownKindsResult:
    """Load one target project's known kinds away from the UI thread."""
    workspace = Path(workspace_dir) if workspace_dir else None
    if workspace is None:
        workspace = known_project_namespaces().get(project) if project else Path.cwd()
    if workspace is None:
        return _KnownKindsResult(project, frozenset(BUILTIN_ARTIFACT_REF_KINDS))

    try:
        context = artifact_ref_context(
            workspace,
            workspace_num if workspace_num > 0 else 1,
            project=project,
        )
    except Exception:
        return _KnownKindsResult(project, frozenset(BUILTIN_ARTIFACT_REF_KINDS))
    return _KnownKindsResult(project, frozenset(context.known_kinds))


class ArtifactRefHighlightMixin(_MixinBase):
    """Overlay known artifact references without doing I/O while typing."""

    if TYPE_CHECKING:
        _artifact_ref_known_kinds_by_project: dict[str | None, frozenset[str]]
        _artifact_ref_kind_worker_projects: dict[str, str | None]
        _artifact_ref_kinds_warming: set[str | None]

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
        self._artifact_ref_kinds_warming = set()
        self._artifact_ref_kind_worker_projects = {}
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
        encoded = text.encode("utf-8")
        if len(encoded) > _MAX_OVERLAY_BYTES:
            return
        if text.count("\n") > _MAX_OVERLAY_LINES:
            return

        try:
            candidates = scan_artifact_refs(text)
            literal_ranges = literal_zone_ranges(text)
        except Exception:
            return
        if not candidates:
            return

        converted = _candidate_character_spans(text, encoded, candidates)
        known_kinds = self._get_warm_artifact_ref_known_kinds()
        literal_index = 0
        for candidate, spans in zip(candidates, converted, strict=True):
            candidate_span = spans["candidate"]
            while (
                literal_index < len(literal_ranges)
                and literal_ranges[literal_index][1] <= candidate_span.start
            ):
                literal_index += 1
            if (
                literal_index < len(literal_ranges)
                and literal_ranges[literal_index][0] < candidate_span.end
            ):
                continue

            if known_kinds is None:
                self._append_artifact_ref_span(
                    candidate_span,
                    "artifact_ref.neutral",
                )
                continue
            if candidate.well_formed and candidate.kind not in known_kinds:
                self._append_artifact_ref_span(
                    candidate_span,
                    "artifact_ref.unknown",
                )
                continue
            for part in ("sigil", "kind", "separator", "payload", "fragment"):
                span = spans.get(part)
                if span is not None:
                    self._append_artifact_ref_span(
                        span,
                        f"artifact_ref.{part}",
                    )

    def _append_artifact_ref_span(
        self,
        span: ArtifactRefSpan,
        style_name: str,
    ) -> None:
        self._append_highlight_span(span.start, span.end, style_name)

    def _get_warm_artifact_ref_known_kinds(self) -> frozenset[str] | None:
        """Return the current project's memory-only known-kind set."""
        try:
            project = self._xprompt_arg_assist_project_from_text()
        except Exception:
            project = None
        return self._artifact_ref_known_kinds_by_project.get(project)

    def _warm_current_artifact_ref_known_kinds(self) -> None:
        """Warm project roles in a worker for disk-free prompt highlighting."""
        if not callable(getattr(self.app, "get_prompt_completion_settings", None)):
            return
        project = self._xprompt_arg_assist_project_from_text()
        if (
            project in self._artifact_ref_known_kinds_by_project
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
        self.run_worker(
            lambda: _load_known_artifact_ref_kinds(
                project,
                workspace_dir,
                workspace_num,
            ),
            name=worker_name,
            group=_ARTIFACT_REF_WORKER_GROUP,
            thread=True,
        )

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
                self._artifact_ref_known_kinds_by_project[result.project] = result.kinds
                self._artifact_ref_kinds_warming.discard(result.project)
                self._artifact_ref_kind_worker_projects.pop(event.worker.name, None)
                self._build_highlight_map()
                self.refresh()
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

    def _register_artifact_ref_text_area_theme(
        self,
        theme_name: str | None = None,
        *,
        apply: bool = True,
    ) -> None:
        active_name = theme_name or str(getattr(self, "theme", "css") or "css")
        base = self._resolve_artifact_ref_base_theme(active_name)
        syntax_styles = dict(base.syntax_styles)
        app_theme = self.app.current_theme
        background = app_theme.background or "#000000"
        argument_color = derive_argument_color(
            app_theme.success,
            foreground=app_theme.foreground,
            background=background,
        )
        fragment_color = derive_argument_color(
            app_theme.accent,
            foreground=app_theme.foreground,
            background=background,
        )
        syntax_styles.update(
            {
                "artifact_ref.sigil": Style(
                    color=app_theme.secondary,
                    bold=True,
                ),
                "artifact_ref.kind": Style(
                    color=app_theme.success,
                    bold=True,
                ),
                "artifact_ref.separator": Style(
                    color=app_theme.secondary,
                    dim=True,
                    bold=True,
                ),
                "artifact_ref.payload": Style(color=argument_color),
                "artifact_ref.fragment": Style(
                    color=fragment_color,
                    italic=True,
                ),
                "artifact_ref.unknown": Style(
                    color=app_theme.foreground,
                    dim=True,
                    italic=True,
                ),
                "artifact_ref.neutral": Style(
                    color=app_theme.secondary,
                    dim=True,
                ),
            }
        )
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


def _candidate_character_spans(
    text: str,
    encoded: bytes,
    candidates: tuple[ArtifactRefPromptCandidate, ...],
) -> tuple[dict[str, ArtifactRefSpan], ...]:
    """Convert scanner byte spans to TextArea's Python-character offsets."""
    span_rows = tuple(_candidate_spans(candidate) for candidate in candidates)
    if len(encoded) == len(text):
        return span_rows

    offsets = {
        value
        for spans in span_rows
        for span in spans.values()
        for value in (span.start, span.end)
    }
    converted: dict[int, int] = {}
    byte_offset = 0
    for character_offset, character in enumerate(text):
        if byte_offset in offsets:
            converted[byte_offset] = character_offset
        byte_offset += len(character.encode("utf-8"))
    if byte_offset in offsets:
        converted[byte_offset] = len(text)
    return tuple(
        {
            part: ArtifactRefSpan(
                start=converted[span.start],
                end=converted[span.end],
            )
            for part, span in spans.items()
        }
        for spans in span_rows
    )


def _candidate_spans(
    candidate: ArtifactRefPromptCandidate,
) -> dict[str, ArtifactRefSpan]:
    spans = {
        "candidate": candidate.candidate_span,
        "sigil": candidate.sigil_span,
        "kind": candidate.kind_span,
        "separator": candidate.separator_span,
        "payload": candidate.payload_span,
    }
    if candidate.fragment_span is not None:
        spans["fragment"] = candidate.fragment_span
    return spans


__all__ = ["ArtifactRefHighlightMixin"]
