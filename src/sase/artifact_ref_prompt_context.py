"""Explicit per-segment prompt-reference resolution context.

Builtin refs (``@stitch``, ``@patch``, short-id ``@bead``, ``@agent``) resolve
against an explicit :class:`PromptRefContext` derived from the prompt's
``#git``/``#gh`` workflow tag, never from ``cwd``. See epic
``plans:202608/artifact_ref_contract.md`` (S3.6-S3.7) and phase plan
``plans:202608/builtin_refs_and_prompt_ref_context.md`` (S3.1).

Every lookup here is best-effort: a failed store, VCS, or registry read
degrades to a less specific context rather than raising, so a malformed or
unrecognized VCS tag never crashes prompt processing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
from typing import Literal

from sase.artifact_ref_models import ArtifactRefContext
from sase.core.paths import sase_projects_dir


log = logging.getLogger(__name__)

_SEGMENT_SEPARATOR_RE = re.compile(r"^---\s*$", re.MULTILINE)
_WORKFLOW_TYPE_RE = re.compile(r"^#([a-zA-Z_][a-zA-Z0-9_]*)")
_WORKSPACE_NUM_ENV_VARS = (
    "SASE_AGENT_WORKSPACE_NUM",
    "SASE_GIT_WORKSPACE_NUM",
    "SASE_GH_WORKSPACE_NUM",
)


@dataclass(frozen=True, slots=True)
class PromptRefProject:
    """The in-context project's identity and both ProjectSpec paths."""

    key: str
    display_name: str
    active_spec: Path
    archive_spec: Path


@dataclass(frozen=True, slots=True)
class PromptRefContext:
    """Explicit resolution context for one prompt segment's builtin refs."""

    artifact_context: ArtifactRefContext
    project: PromptRefProject | None
    primary_repo: str | None
    workspace_dir: Path | None
    workspace_num: int | None
    origin: Literal["vcs_workflow", "launch_identity", "explicit", "none"]
    vcs_ref: str | None = None


def prompt_ref_context_for_vcs_ref(
    vcs_tag: str,
    *,
    is_home_mode: bool,
    workspace_num: int | None = None,
) -> PromptRefContext:
    """Build a context from one prompt segment's ``#git``/``#gh`` tag."""

    workflow_type, ref = _tag_identity(vcs_tag)

    key: str | None = None
    if ref is not None:
        try:
            from sase.project_display_names import load_project_ref_display_snapshot

            snapshot = load_project_ref_display_snapshot()
            key = snapshot.project_key_for_ref(ref)
        except Exception:
            log.debug(
                "Unable to resolve project key for VCS ref %r", ref, exc_info=True
            )
            key = None

    project = (
        _prompt_ref_project_for_key(key) if key is not None and key != "home" else None
    )
    resolved_workspace_num = (
        workspace_num
        if workspace_num is not None
        else _resolved_workspace_num(is_home_mode)
    )
    workspace_dir = _workspace_dir_for_ref(ref, key=key, workflow_type=workflow_type)
    artifact_context = _safe_artifact_ref_context(
        workspace_dir,
        resolved_workspace_num,
        project=key or ref or "home",
    )

    return PromptRefContext(
        artifact_context=artifact_context,
        project=project,
        primary_repo=_primary_repo_name(artifact_context),
        workspace_dir=workspace_dir,
        workspace_num=resolved_workspace_num,
        origin="vcs_workflow",
        vcs_ref=ref,
    )


def prompt_ref_context_from_launch_identity(*, is_home_mode: bool) -> PromptRefContext:
    """Build a context from the launcher's own recorded segment identity."""

    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    active_dir = os.environ.get("SASE_ACTIVE_PROJECT_DIR")

    key: str | None = None
    if project_file:
        try:
            key = Path(project_file).parent.name or None
        except (OSError, ValueError):
            key = None

    project = (
        _prompt_ref_project_for_key(key) if key is not None and key != "home" else None
    )

    workspace_dir: Path | None = None
    if active_dir:
        try:
            workspace_dir = Path(active_dir).expanduser().resolve(strict=False)
        except (OSError, ValueError):
            workspace_dir = None

    resolved_workspace_num = _resolved_workspace_num(is_home_mode)
    artifact_context = _safe_artifact_ref_context(
        workspace_dir,
        resolved_workspace_num,
        project=key or "home",
    )

    return PromptRefContext(
        artifact_context=artifact_context,
        project=project,
        primary_repo=_primary_repo_name(artifact_context),
        workspace_dir=workspace_dir,
        workspace_num=resolved_workspace_num,
        origin="launch_identity",
        vcs_ref=None,
    )


def empty_prompt_ref_context(*, is_home_mode: bool) -> PromptRefContext:
    """Build a no-project context: short forms fail actionably, qualified forms resolve."""

    return PromptRefContext(
        artifact_context=_minimal_artifact_ref_context(),
        project=None,
        primary_repo=None,
        workspace_dir=None,
        workspace_num=_resolved_workspace_num(is_home_mode),
        origin="none",
        vcs_ref=None,
    )


def explicit_prompt_ref_context(context: ArtifactRefContext) -> PromptRefContext:
    """Wrap a caller-supplied context unchanged.

    For the CLI and test callers where a context is already known and the
    user's working directory is the intentional source of truth (unlike the
    prompt path, which never infers from ``cwd``).
    """

    return PromptRefContext(
        artifact_context=context,
        project=None,
        primary_repo=_primary_repo_name(context),
        workspace_dir=None,
        workspace_num=None,
        origin="explicit",
        vcs_ref=None,
    )


def prompt_ref_contexts_for_prompt(
    prompt: str,
    *,
    is_home_mode: bool,
    ref_contexts: Sequence[PromptRefContext] | None = None,
) -> tuple[tuple[tuple[int, int], PromptRefContext], ...]:
    """Return one ``(character_span, context)`` pair per top-level segment.

    Resolution order per segment, matching the epic's prompt-processing
    contract: (1) the segment's own VCS tag, if it still carries one --
    including after embedded-workflow expansion, since a segment whose tag
    was already consumed simply has none left and falls through; (2) the
    caller-supplied *ref_contexts* entry at this segment's index; (3) the
    single *ref_contexts* entry, when exactly one was supplied (the common
    single-segment launch, and the safe answer when embedded expansion
    changed the segment count); (4) the launcher's own recorded identity.

    Contexts built from a VCS tag are memoized by ``(workflow_type, ref,
    workspace_num)`` so an N-segment prompt on one project builds one
    :class:`~sase.artifact_ref_models.ArtifactRefContext`.
    """

    segments = _prompt_segments(prompt)
    if ref_contexts is not None and len(ref_contexts) not in (0, 1, len(segments)):
        log.debug(
            "prompt has %d segments but %d ref_contexts were supplied; "
            "falling back per unmatched segment",
            len(segments),
            len(ref_contexts),
        )

    single = (
        ref_contexts[0] if ref_contexts is not None and len(ref_contexts) == 1 else None
    )
    workspace_num = _resolved_workspace_num(is_home_mode)
    memo: dict[tuple[str | None, str | None, int], PromptRefContext] = {}
    launch_identity_context: PromptRefContext | None = None
    results: list[tuple[tuple[int, int], PromptRefContext]] = []
    for index, (span, text) in enumerate(segments):
        tag = _leading_or_embedded_tag(text)
        if tag is not None:
            cache_key = (*_tag_identity(tag), workspace_num)
            context = memo.get(cache_key)
            if context is None:
                context = prompt_ref_context_for_vcs_ref(
                    tag, is_home_mode=is_home_mode, workspace_num=workspace_num
                )
                memo[cache_key] = context
        elif ref_contexts is not None and index < len(ref_contexts):
            context = ref_contexts[index]
        elif single is not None:
            context = single
        else:
            if launch_identity_context is None:
                launch_identity_context = prompt_ref_context_from_launch_identity(
                    is_home_mode=is_home_mode
                )
            context = launch_identity_context
        results.append((span, context))
    return tuple(results)


def prompt_segment_vcs_refs(prompt: str) -> tuple[str | None, ...]:
    """Return each top-level segment's own VCS tag, or ``None`` when it has none.

    Meant to be captured from the prompt :func:`preprocess_prompt_early`
    returns, before embedded-workflow expansion can consume a segment's tag.
    """

    return tuple(
        _leading_or_embedded_tag(text) for _span, text in _prompt_segments(prompt)
    )


def prompt_ref_contexts_for_segment_vcs_refs(
    segment_vcs_refs: Sequence[str | None],
    *,
    is_home_mode: bool,
) -> tuple[PromptRefContext, ...]:
    """Build one context per captured segment VCS ref (or launch identity)."""

    launch_identity_context: PromptRefContext | None = None
    contexts: list[PromptRefContext] = []
    for ref in segment_vcs_refs:
        if ref is not None:
            contexts.append(
                prompt_ref_context_for_vcs_ref(ref, is_home_mode=is_home_mode)
            )
            continue
        if launch_identity_context is None:
            launch_identity_context = prompt_ref_context_from_launch_identity(
                is_home_mode=is_home_mode
            )
        contexts.append(launch_identity_context)
    return tuple(contexts)


def _prompt_segments(prompt: str) -> tuple[tuple[tuple[int, int], str], ...]:
    """Split *prompt* into top-level ``---``-separated segments with spans.

    Mirrors ``xprompt._parsing_vcs_tags``'s segment splitting (protect
    fenced/inline code before splitting on the separator, then restore each
    piece) without frontmatter handling: by the time a prompt reaches late
    preprocessing, ``parse_multi_prompt`` has already stripped any leading
    YAML frontmatter block and rejoined segments with the same separator.
    """

    from sase.xprompt._fenced_blocks import (
        protect_fenced_blocks,
        unprotect_fenced_blocks,
    )

    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)
    pieces = _SEGMENT_SEPARATOR_RE.split(protected)
    separators = _SEGMENT_SEPARATOR_RE.findall(protected)

    segments: list[tuple[tuple[int, int], str]] = []
    offset = 0
    for index, piece in enumerate(pieces):
        restored = unprotect_fenced_blocks(piece, fenced_blocks)
        start = offset
        end = start + len(restored)
        segments.append(((start, end), restored))
        offset = end
        if index < len(separators):
            offset += len(separators[index])
    return tuple(segments)


def _leading_or_embedded_tag(segment: str) -> str | None:
    from sase.xprompt._parsing_vcs_tags import (
        extract_vcs_workflow_tag,
        find_vcs_workflow_tag,
    )

    tag = extract_vcs_workflow_tag(segment)
    if tag is not None:
        return tag
    return find_vcs_workflow_tag(segment)


def _tag_identity(tag: str) -> tuple[str | None, str | None]:
    from sase.xprompt._parsing_vcs_refs import normalize_vcs_underscore_refs
    from sase.xprompt._parsing_vcs_tags import extract_project_from_vcs_tag

    normalized = normalize_vcs_underscore_refs(tag)
    match = _WORKFLOW_TYPE_RE.match(normalized.strip())
    workflow_type = match.group(1) if match else None
    return workflow_type, extract_project_from_vcs_tag(normalized)


def _workspace_num_from_environment() -> int | None:
    for name in _WORKSPACE_NUM_ENV_VARS:
        raw = os.environ.get(name)
        if raw is None:
            continue
        try:
            return int(raw)
        except ValueError:
            continue
    return None


def _resolved_workspace_num(is_home_mode: bool) -> int:
    from_env = _workspace_num_from_environment()
    if from_env is not None:
        return from_env
    return 0 if is_home_mode else 1


def _workspace_dir_for_ref(
    ref: str | None,
    *,
    key: str | None,
    workflow_type: str | None,
) -> Path | None:
    # 1. The launch identity's SASE_ACTIVE_PROJECT_DIR, when it belongs to
    #    this same project key.
    if key is not None:
        project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
        active_dir = os.environ.get("SASE_ACTIVE_PROJECT_DIR")
        if project_file and active_dir:
            try:
                launch_key = Path(project_file).parent.name
            except (OSError, ValueError):
                launch_key = None
            if launch_key == key:
                try:
                    return Path(active_dir).expanduser().resolve(strict=False)
                except (OSError, ValueError):
                    pass

    # 2. peek_ref(...).primary_workspace_dir: a read-only registry lookup
    #    that may legitimately return None when no plugin claims the ref.
    if ref is not None and workflow_type is not None:
        try:
            from sase.workspace_provider import peek_ref

            resolved = peek_ref(ref, workflow_type)
        except Exception:
            resolved = None
        if resolved is not None and resolved.primary_workspace_dir:
            try:
                return (
                    Path(resolved.primary_workspace_dir)
                    .expanduser()
                    .resolve(strict=False)
                )
            except (OSError, ValueError):
                pass

    # 3. The kind == "primary" repo record's path.
    if key is not None:
        try:
            from sase.repo_inventory import collect_repo_inventory

            inventory = collect_repo_inventory(project=key)
        except Exception:
            inventory = None
        if inventory is not None:
            for record in inventory.records:
                if getattr(record, "kind", None) != "primary":
                    continue
                path = getattr(record, "path", None)
                if path:
                    try:
                        return Path(str(path)).expanduser().resolve(strict=False)
                    except (OSError, ValueError):
                        pass
                break
    return None


def _prompt_ref_project_for_key(key: str) -> PromptRefProject | None:
    from sase.ace.patch.project_spec_path import preferred_project_spec_path
    from sase.core.project_lifecycle_facade import list_project_records
    from sase.core.project_lifecycle_wire import effective_project_name

    try:
        records = list_project_records(sase_projects_dir(), "all", include_home=True)
    except Exception:
        log.debug("Unable to list project records for %r", key, exc_info=True)
        records = []

    display_name = key
    for record in records:
        if record.project_name == key:
            display_name = effective_project_name(record)
            break

    project_dir = str(sase_projects_dir() / key)
    try:
        active_spec = Path(preferred_project_spec_path(project_dir, key))
        archive_spec = Path(preferred_project_spec_path(project_dir, key, archive=True))
    except Exception:
        log.debug("Unable to resolve ProjectSpec paths for %r", key, exc_info=True)
        return None

    return PromptRefProject(
        key=key,
        display_name=display_name,
        active_spec=active_spec,
        archive_spec=archive_spec,
    )


def _primary_repo_name(artifact_context: ArtifactRefContext) -> str | None:
    for repository in artifact_context.repositories:
        if repository.kind == "primary":
            return repository.name
    return None


def _minimal_artifact_ref_context() -> ArtifactRefContext:
    """An empty, workspace-independent context: no cwd, no guessing."""

    from sase.core.artifact_file_facade import default_artifact_files_index_path
    from sase.core.paths import sase_subdir

    return ArtifactRefContext(
        document_roots=(),
        chats_root=sase_subdir("chats").expanduser().resolve(strict=False),
        artifact_index_path=default_artifact_files_index_path()
        .expanduser()
        .resolve(strict=False),
        repositories=(),
        projects=(),
    )


def _safe_artifact_ref_context(
    workspace_dir: Path | None,
    workspace_num: int,
    *,
    project: str,
) -> ArtifactRefContext:
    if workspace_dir is None:
        return _minimal_artifact_ref_context()

    from sase.artifact_ref_context import artifact_ref_context

    try:
        return artifact_ref_context(workspace_dir, workspace_num, project=project)
    except Exception:
        log.debug(
            "Unable to build artifact-reference context for workspace %r",
            workspace_dir,
            exc_info=True,
        )
        return _minimal_artifact_ref_context()


__all__ = [
    "PromptRefContext",
    "PromptRefProject",
    "empty_prompt_ref_context",
    "explicit_prompt_ref_context",
    "prompt_ref_context_for_vcs_ref",
    "prompt_ref_context_from_launch_identity",
    "prompt_ref_contexts_for_prompt",
    "prompt_ref_contexts_for_segment_vcs_refs",
    "prompt_segment_vcs_refs",
]
