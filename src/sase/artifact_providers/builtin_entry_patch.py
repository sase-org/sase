"""Python-owned resolution for ``@patch``."""

from __future__ import annotations

import logging

from sase.ace.patch.models import Patch
from sase.artifact_providers.builtin_entries import (
    BuiltinEntryOutcome,
    validate_builtin_entry,
)
from sase.artifact_ref_models import ArtifactEntry, ArtifactRef, ArtifactRefContext
from sase.artifact_ref_operations import (
    artifact_ref_expansion_render,
    artifact_ref_expansion_validate,
)
from sase.artifact_ref_prompt_context import PromptRefContext, PromptRefProject


log = logging.getLogger(__name__)

_PATCH_EXPANSION_FORMAT = (
    "the {display_label} Patch in project {project} "
    "(inspect with `sase patch show {display_label}`)"
)
# Fail fast at import time rather than deep inside a Rust-side .format() call
# if a future edit lets the format string and its substitution dict drift.
_PATCH_EXPANSION_PLACEHOLDERS = frozenset(
    artifact_ref_expansion_validate(_PATCH_EXPANSION_FORMAT)
)


def resolve_patch_entry(
    reference: ArtifactRef,
    *,
    context: ArtifactRefContext,
    ref_context: PromptRefContext,
) -> BuiltinEntryOutcome:
    name = reference.payload.name or ""

    if ref_context.project is not None:
        project = ref_context.project.display_name
        patch = _resolve_in_project(name, ref_context.project)
        if patch is None:
            return BuiltinEntryOutcome(
                status="missing",
                candidates=(
                    str(ref_context.project.active_spec),
                    str(ref_context.project.archive_spec),
                ),
            )
    else:
        found = _resolve_across_projects(name)
        if isinstance(found, BuiltinEntryOutcome):
            return found
        patch = found
        project = patch.project_display_name or ""

    entry = validate_builtin_entry(
        ArtifactEntry(
            stable_id=f"patch:{project}/{patch.name}",
            ref_kind="patch",
            canonical_argument=patch.name,
            display_label=patch.name,
            origin="prompt_ref",
            project_display_name=project,
            properties=_patch_properties(patch, project),
        )
    )
    patch_values = {"display_label": patch.name, "project": project}
    assert set(patch_values) == _PATCH_EXPANSION_PLACEHOLDERS
    prompt_text = artifact_ref_expansion_render(_PATCH_EXPANSION_FORMAT, patch_values)
    return BuiltinEntryOutcome(
        status="exact",
        entry=entry,
        prompt_text=prompt_text,
        locator=f"{project}/{patch.name}",
        resolved_path=None,
    )


def _resolve_in_project(name: str, project: PromptRefProject) -> Patch | None:
    try:
        from sase.ace.patch.cache import get_global_snapshot_cache

        cache = get_global_snapshot_cache()
        # Active spec wins over archive when both match.
        for spec_path in (project.active_spec, project.archive_spec):
            for patch in cache.get_file_specs(spec_path, project.display_name):
                if patch.name == name:
                    return patch
    except Exception:
        log.debug(
            "Unable to look up Patch %r for project %r",
            name,
            project.key,
            exc_info=True,
        )
    return None


def _resolve_across_projects(name: str) -> Patch | BuiltinEntryOutcome:
    try:
        from sase.ace.patch.cache import find_all_patches_cached

        matches = [
            patch
            for patch in find_all_patches_cached(include_states=("enabled",))
            if patch.name == name
        ]
    except Exception:
        log.debug("Unable to search Patches by name %r", name, exc_info=True)
        matches = []

    if not matches:
        return BuiltinEntryOutcome(status="missing")
    if len(matches) > 1:
        candidates = tuple(
            f"{patch.project_display_name}: {patch.name}" for patch in matches
        )
        return BuiltinEntryOutcome(
            status="ambiguous",
            candidates=candidates,
            diagnostic=(
                f"@patch:{name} is ambiguous across projects; add a #git/#gh "
                "workflow to the prompt segment"
            ),
        )
    return matches[0]


def _patch_properties(patch: Patch, project: str) -> dict[str, str]:
    properties = {"project": project, "status": patch.status}
    if patch.parent:
        properties["parent"] = patch.parent
    if patch.pr_url:
        properties["pr"] = patch.pr_url
    properties["mentors"] = str(len(patch.mentors or ()))
    properties["stitch_count"] = str(len(patch.stitches or ()))
    return properties


__all__ = ["resolve_patch_entry"]
