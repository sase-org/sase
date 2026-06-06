"""Resolve the filesystem base for prompt path completion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re

_KNOWN_PROJECT_ONLY_WORKFLOW_TYPES = frozenset({"git"})
"""Registered workflows whose resolver can create project/workspace state."""


@dataclass(frozen=True, slots=True)
class _PromptWorkflowRef:
    start: int
    workflow_type: str
    ref: str


def resolve_prompt_completion_base_dir(prompt: str) -> str | None:
    """Return the prompt-selected base directory for path completion.

    This helper is intentionally read-only: it never changes process CWD,
    claims workspaces, or activates lifecycle projects.  When a ref is
    incomplete or cannot be resolved, ``None`` is returned so callers keep the
    existing CWD-based behavior.
    """
    if "#" not in prompt:
        return None

    normalized = _normalize_prompt_refs(prompt)
    patterns = _get_ref_patterns()
    if not patterns:
        return _known_project_base_dir(normalized)

    cd_base = _resolve_cd_base_dir(normalized, patterns)
    if cd_base is not None:
        return cd_base
    if _has_cd_ref(normalized, patterns):
        return None

    known_projects: dict[str, Any] | None = None
    for prompt_ref in _iter_registered_refs(normalized, patterns, exclude={"cd"}):
        if prompt_ref.workflow_type in _KNOWN_PROJECT_ONLY_WORKFLOW_TYPES:
            known_projects = _ensure_known_projects_loaded(known_projects)
            base_dir = _known_project_base_dir_for_ref(
                prompt_ref.ref,
                known_projects,
            )
            if base_dir is not None:
                return base_dir
            continue

        base_dir = _resolve_registered_base_dir(
            prompt_ref.ref,
            prompt_ref.workflow_type,
        )
        if base_dir is not None:
            return base_dir

    return _known_project_base_dir(normalized, known_projects=known_projects)


def _normalize_prompt_refs(prompt: str) -> str:
    try:
        from sase.project_aliases import canonicalize_project_aliases_in_prompt

        prompt = canonicalize_project_aliases_in_prompt(prompt)
    except Exception:
        pass

    try:
        from sase.xprompt._parsing import normalize_vcs_underscore_refs

        return normalize_vcs_underscore_refs(prompt)
    except Exception:
        return prompt


def _get_ref_patterns() -> dict[str, re.Pattern[str]]:
    try:
        from sase.workspace_provider import get_ref_patterns

        return get_ref_patterns()
    except Exception:
        return {}


def _resolve_cd_base_dir(
    prompt: str,
    patterns: dict[str, re.Pattern[str]],
) -> str | None:
    pattern = patterns.get("cd")
    if pattern is None:
        return None
    match = pattern.search(prompt)
    if match is None:
        return None
    ref = _ref_from_match(match)
    if not ref:
        return None
    return _resolve_registered_base_dir(ref, "cd")


def _has_cd_ref(prompt: str, patterns: dict[str, re.Pattern[str]]) -> bool:
    pattern = patterns.get("cd")
    return pattern is not None and pattern.search(prompt) is not None


def _iter_registered_refs(
    prompt: str,
    patterns: dict[str, re.Pattern[str]],
    *,
    exclude: set[str],
) -> list[_PromptWorkflowRef]:
    refs: list[_PromptWorkflowRef] = []
    for workflow_type, pattern in patterns.items():
        if workflow_type in exclude:
            continue
        for match in pattern.finditer(prompt):
            ref = _ref_from_match(match)
            if ref:
                refs.append(_PromptWorkflowRef(match.start(), workflow_type, ref))
    refs.sort(key=lambda item: item.start)
    return refs


def _ref_from_match(match: re.Match[str]) -> str | None:
    for group in (1, 2):
        try:
            value = match.group(group)
        except IndexError:
            continue
        if value:
            return value
    return None


def _resolve_registered_base_dir(ref: str, workflow_type: str) -> str | None:
    try:
        from sase.workspace_provider import resolve_ref

        resolved = resolve_ref(ref, workflow_type)
    except Exception:
        return None

    base_dir = resolved.primary_workspace_dir
    return str(base_dir) if base_dir else None


def _known_project_base_dir(
    prompt: str,
    *,
    known_projects: dict[str, Any] | None = None,
) -> str | None:
    known_projects = _ensure_known_projects_loaded(known_projects)
    if not known_projects:
        return None

    try:
        from sase.xprompt._parsing import iter_known_project_vcs_refs

        refs = iter_known_project_vcs_refs(prompt, known_projects)
    except Exception:
        return None

    for _workflow_type, ref in refs:
        base_dir = _known_project_base_dir_for_ref(ref, known_projects)
        if base_dir is not None:
            return base_dir
    return None


def _ensure_known_projects_loaded(
    known_projects: dict[str, Any] | None,
) -> dict[str, Any]:
    if known_projects is not None:
        return known_projects
    return _load_known_project_workspaces()


def _load_known_project_workspaces() -> dict[str, Any]:
    try:
        from sase.xprompt.loader import get_known_project_workspaces

        try:
            return dict(get_known_project_workspaces(include_states="all"))
        except TypeError as exc:
            if "include_states" not in str(exc):
                raise
            return dict(get_known_project_workspaces())
    except Exception:
        return {}


def _known_project_base_dir_for_ref(
    ref: str,
    known_projects: dict[str, Any],
) -> str | None:
    try:
        from sase.xprompt._parsing import resolve_known_project_ref

        project = resolve_known_project_ref(ref, known_projects)
    except Exception:
        return None
    if project is None:
        return None

    path = _workspace_path(known_projects.get(project))
    return None if path is None else str(path)


def _workspace_path(value: Any) -> Path | None:
    if isinstance(value, Path):
        return value
    if isinstance(value, str):
        return Path(value)

    workspace_dir = getattr(value, "workspace_dir", None)
    if isinstance(workspace_dir, Path):
        return workspace_dir
    if isinstance(workspace_dir, str) and workspace_dir:
        return Path(workspace_dir)
    return None
