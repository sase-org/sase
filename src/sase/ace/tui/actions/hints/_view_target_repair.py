"""Repair logical plan and archived-prompt targets selected from file hints."""

from __future__ import annotations

import re
from pathlib import Path

from sase._linked_repo_paths import hidden_sidecar_clone_dir
from sase.sdd.store import AGENTS_SIDECAR_ROLE
from sase.sdd.plan_refs import resolve_plan_reference
from sase.pager.link_context import LinkResolutionContext

_ARCHIVED_PROMPT_TAIL_RE = re.compile(
    r"(?:^|/)(prompts/\d{6}/[^/\s<>()\[\]{}'\"`]+\.md)$"
)


def resolve_logical_plan_target(
    ref: str,
    link_context: LinkResolutionContext,
) -> str | None:
    """Resolve a selected plan identity through the captured context anchors."""
    for anchor in link_context.anchors:
        try:
            resolution = resolve_plan_reference(
                ref,
                workspace_dir=anchor.directory,
                workspace_num=anchor.workspace_num or 1,
            )
        except (ValueError, RuntimeError, OSError):
            continue
        resolved_path = resolution.resolved_path
        if resolved_path is not None and resolved_path.is_file():
            return str(resolved_path)
    return None


def repair_archived_prompt_path(
    path: str,
    project_file: str | None,
) -> str | None:
    """Find a missing archived-prompt hint in its project's agents sidecar."""
    if not project_file:
        return None
    match = _ARCHIVED_PROMPT_TAIL_RE.search(Path(path).as_posix())
    if match is None:
        return None
    try:
        project_key = Path(project_file).parent.name
        agents_root = Path(hidden_sidecar_clone_dir(project_key, AGENTS_SIDECAR_ROLE))
        target = agents_root / match.group(1)
        if target.is_file():
            return str(target)
    except (OSError, RuntimeError, ValueError):
        return None
    return None
