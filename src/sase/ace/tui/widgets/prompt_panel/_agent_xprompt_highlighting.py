"""Shared xprompt-highlighting context for agent prompt panels."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.ace.tui.util.artifact_ref_syntax import (
    ArtifactRefStylePalette,
    apply_artifact_ref_overlays,
    artifact_ref_style_palette_from_theme,
)
from sase.ace.tui.glossary_catalog import PromptGlossaryContext
from sase.ace.tui.repo_mention_catalog import PromptRepoMentionContext
from sase.ace.tui.util.lazy_syntax import (
    MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES,
    MARKDOWN_SYNTAX_HIGHLIGHT_MAX_LINES,
)
from sase.ace.tui.util.semantic_overlay import apply_semantic_overlays
from sase.ace.tui.util.semantic_styles import (
    SemanticHighlightStyles,
    semantic_highlight_styles_from_theme,
)
from sase.ace.tui.util.xprompt_syntax import apply_xprompt_overlays
from sase.artifact_refs import parsable_artifact_ref_kinds
from sase.xprompt import extract_project_from_vcs_tag, extract_vcs_workflow_tag
from sase.xprompt.glossary_catalog import EditorGlossaryCatalog
from sase.xprompt.repo_mention_catalog import EditorRepoMentionCatalog

from ...models.agent import Agent


@dataclass(frozen=True, slots=True)
class AgentPromptHighlightContext:
    """Memory-only semantic context for one agent's authored prompt bodies."""

    project: str | None
    workspace: str | None
    known_skills: frozenset[str]
    glossary_catalog: EditorGlossaryCatalog | None
    repo_catalog: EditorRepoMentionCatalog | None
    styles: SemanticHighlightStyles | None
    artifact_ref_known_kinds: frozenset[str]
    artifact_ref_styles: ArtifactRefStylePalette
    fingerprint: tuple[object, ...]

    @property
    def has_semantic_catalogs(self) -> bool:
        return self.glossary_catalog is not None or self.repo_catalog is not None


def _agent_project_and_workspace(
    agent: Agent,
    raw_xprompt: str,
) -> tuple[str | None, str | None]:
    """Resolve the project ref and launch workspace for *agent* without I/O."""
    project: str | None = None
    if raw_xprompt:
        try:
            vcs_tag = extract_vcs_workflow_tag(raw_xprompt)
            if vcs_tag is not None:
                project = extract_project_from_vcs_tag(vcs_tag)
        except Exception:
            project = None

    if project is None and agent.project_file:
        project = Path(agent.project_file).parent.name or None

    workspace: str | None = None
    if isinstance(agent.workspace_dir, str) and agent.workspace_dir:
        workspace = agent.workspace_dir
    return project, workspace


def agent_prompt_highlight_context(
    panel: object,
    agent: Agent,
    raw_xprompt: str,
    *,
    schedule: bool = True,
) -> AgentPromptHighlightContext:
    """Return catalogs, styles, and a conservative cache fingerprint for *agent*.

    Catalogs are read only through the app's in-memory getters. *schedule*
    may request an asynchronous warm; it never reads the filesystem.
    """
    project, workspace = _agent_project_and_workspace(agent, raw_xprompt)
    known_skills = _known_skills_for_project(panel, project, schedule=schedule)
    catalog_context = PromptGlossaryContext(
        project_ref=project,
        launch_workspace=workspace,
    )
    repo_context = PromptRepoMentionContext(
        project_ref=project,
        launch_workspace=workspace,
    )
    app = _panel_app(panel)
    glossary_value, glossary_warm = _memory_catalog(
        app,
        "get_prompt_glossary_catalog",
        "is_prompt_glossary_catalog_warm",
        catalog_context,
        schedule=schedule,
    )
    repo_value, repo_warm = _memory_catalog(
        app,
        "get_prompt_repo_mention_catalog",
        "is_prompt_repo_mention_catalog_warm",
        repo_context,
        schedule=schedule,
    )
    glossary_catalog = (
        glossary_value if isinstance(glossary_value, EditorGlossaryCatalog) else None
    )
    repo_catalog = (
        repo_value if isinstance(repo_value, EditorRepoMentionCatalog) else None
    )
    styles = None
    artifact_ref_styles = artifact_ref_style_palette_from_theme(None)
    if app is not None:
        try:
            styles = semantic_highlight_styles_from_theme(
                getattr(app, "current_theme", None)
            )
        except Exception:
            styles = None
        try:
            artifact_ref_styles = artifact_ref_style_palette_from_theme(
                getattr(app, "current_theme", None)
            )
        except Exception:
            artifact_ref_styles = artifact_ref_style_palette_from_theme(None)
    artifact_ref_known_kinds = _artifact_ref_known_kinds()
    fingerprint = (
        frozenset(known_skills),
        _catalog_fingerprint(
            glossary_catalog,
            warm=glossary_warm,
            kind="glossary",
        ),
        _catalog_fingerprint(
            repo_catalog,
            warm=repo_warm,
            kind="repo",
        ),
        styles.signature if styles is not None else "",
        artifact_ref_styles.signature,
        artifact_ref_known_kinds,
    )
    return AgentPromptHighlightContext(
        project=project,
        workspace=workspace,
        known_skills=known_skills,
        glossary_catalog=glossary_catalog,
        repo_catalog=repo_catalog,
        styles=styles,
        artifact_ref_known_kinds=artifact_ref_known_kinds,
        artifact_ref_styles=artifact_ref_styles,
        fingerprint=fingerprint,
    )


def apply_authored_prompt_overlays(
    highlighted: Any,
    source: str,
    context: AgentPromptHighlightContext,
    *,
    region_start: int = 0,
    include_xprompt: bool = False,
    hint_spans: tuple[object, ...] = (),
) -> None:
    """Layer glossary/repo, then xprompt, then numbered-hint styles."""
    try:
        apply_semantic_overlays(
            highlighted,
            source,
            glossary_catalog=context.glossary_catalog,
            repo_catalog=context.repo_catalog,
            styles=context.styles,
            region_start=region_start,
            skip_xprompt=include_xprompt,
            known_skills=context.known_skills,
        )
        if include_xprompt:
            apply_xprompt_overlays(
                highlighted,
                source,
                region_start=region_start,
                known_skills=context.known_skills,
            )
            apply_artifact_ref_overlays(
                highlighted,
                source,
                known_kinds=context.artifact_ref_known_kinds,
                palette=context.artifact_ref_styles,
                region_start=region_start,
                max_bytes=MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES,
                max_lines=MARKDOWN_SYNTAX_HIGHLIGHT_MAX_LINES,
            )
        for span in hint_spans:
            style = getattr(span, "style", None)
            start = getattr(span, "start", None)
            end = getattr(span, "end", None)
            if style is None or not isinstance(start, int) or not isinstance(end, int):
                continue
            highlighted.stylize(style, start, end)
    except Exception:
        return


def _artifact_ref_known_kinds() -> frozenset[str]:
    try:
        return frozenset(parsable_artifact_ref_kinds())
    except Exception:
        return frozenset()


def _known_skills_for_project(
    panel: object,
    project: str | None,
    *,
    schedule: bool,
) -> frozenset[str]:
    try:
        app = _panel_app(panel)
        getter = getattr(app, "get_prompt_catalog_assist_entries", None)
        if not callable(getter):
            return frozenset()
        entries = getter(project, schedule=schedule)
        if entries is None:
            return frozenset()
        # ``/foo`` tokens are highlighted by the provider skill name, not the
        # namespaced ``skill/foo`` xprompt reference.
        return frozenset(
            entry.skill_name
            for entry in entries
            if getattr(entry, "is_skill", False)
            and isinstance(getattr(entry, "skill_name", None), str)
        )
    except Exception:
        return frozenset()


def _memory_catalog(
    app: object | None,
    getter_name: str,
    warm_name: str,
    context: object,
    *,
    schedule: bool,
) -> tuple[object | None, bool]:
    if app is None:
        return None, True
    getter = getattr(app, getter_name, None)
    if not callable(getter):
        return None, True
    try:
        catalog = getter(context, schedule=schedule)
    except Exception:
        return None, True
    checker = getattr(app, warm_name, None)
    warm = True
    if callable(checker):
        try:
            warm = bool(checker(context))
        except Exception:
            warm = True
    return catalog, warm


def _catalog_fingerprint(
    catalog: object | None,
    *,
    warm: bool,
    kind: str,
) -> tuple[object, ...]:
    if not warm:
        return (kind, "cold")
    if catalog is None:
        return (kind, "empty")
    if kind == "glossary" and isinstance(catalog, EditorGlossaryCatalog):
        signature = catalog.config_signature
        return (
            kind,
            catalog.project.key,
            signature.path,
            signature.mtime_ns,
            signature.size,
        )
    if kind == "repo" and isinstance(catalog, EditorRepoMentionCatalog):
        return (
            kind,
            catalog.project.key,
            tuple(
                (
                    mention.identifier,
                    mention.kind,
                    mention.config_path,
                    mention.config_line,
                )
                for mention in catalog.mentions
            ),
        )
    return (kind, "unknown")


def _panel_app(panel: object) -> object | None:
    try:
        return getattr(panel, "app", None)
    except Exception:
        return None


__all__ = [
    "AgentPromptHighlightContext",
    "agent_prompt_highlight_context",
    "apply_authored_prompt_overlays",
]
