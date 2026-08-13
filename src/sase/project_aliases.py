"""Public project alias services and VCS ref canonicalization facade."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import (
    apply_project_aliases_update,
    apply_project_name_update,
    list_project_records,
)
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.project_alias_mutations import (
    ProjectAliasError,
    add_project_alias_locked as _add_project_alias_locked,
    remove_project_alias_locked as _remove_project_alias_locked,
    set_project_aliases_locked as _set_project_aliases_locked,
    set_project_name_locked as _set_project_name_locked_impl,
)
from sase.project_alias_records import (
    allocate_project_name,
    filtered_project_records,
    normalize_project_aliases,
    normalize_project_name,
    project_alias_map_from_records,
)

_KNOWN_VCS_WORKFLOW_NAMES = frozenset({"gh", "git", "jj", "p4"})
_REF_CHARS = r"[A-Za-z0-9_./~-]+"
_REF_BOUNDARY = r"(?=$|[\s)\]},.!?;:\"'])"


def _vcs_workflow_names() -> set[str]:
    """Return workflow names whose refs represent project-like VCS targets."""
    from sase.workspace_provider import get_all_workflow_metadata

    names = set(_KNOWN_VCS_WORKFLOW_NAMES)
    for metadata in get_all_workflow_metadata():
        if (
            metadata.workflow_type in _KNOWN_VCS_WORKFLOW_NAMES
            or metadata.vcs_family
            or metadata.vcs_provider_name
        ):
            names.add(metadata.workflow_type)
    return names


def _project_alias_ref_pattern() -> re.Pattern[str] | None:
    names = _vcs_workflow_names()
    if not names:
        return None
    workflows = "|".join(
        re.escape(name) for name in sorted(names, key=lambda item: (-len(item), item))
    )
    return re.compile(
        rf"(?P<context>^|(?<=[\s(\[{{\"']))"
        rf"#(?P<workflow>{workflows})"
        r"(?P<marker>!!|\?\?)?"
        rf"(?:(?P<sep>[:_])(?P<ref>{_REF_CHARS})|\((?P<paren>{_REF_CHARS})\))"
        rf"{_REF_BOUNDARY}",
        re.MULTILINE,
    )


def _projects_root(projects_root: Path | None) -> Path:
    return (
        projects_root.expanduser() if projects_root is not None else sase_projects_dir()
    )


def _invalidate_xprompt_project_identity() -> None:
    from sase.xprompt.project_identity import invalidate_xprompt_project_identity

    invalidate_xprompt_project_identity()


def _filtered_project_records(
    projects_root: Path | str | None,
) -> list[ProjectRecordWire]:
    root = Path(projects_root) if projects_root is not None else sase_projects_dir()
    return filtered_project_records(root, list_project_records=list_project_records)


def set_project_aliases_locked(
    project: str,
    aliases: list[str],
    *,
    projects_root: Path | None = None,
) -> ProjectRecordWire:
    """Replace aliases for *project* while holding the ProjectSpec lock."""
    record = _set_project_aliases_locked(
        project,
        aliases,
        projects_root=_projects_root(projects_root),
        resolve_project_ref=resolve_project_alias_ref,
        list_project_records=list_project_records,
        apply_project_aliases_update=apply_project_aliases_update,
    )
    _invalidate_xprompt_project_identity()
    return record


def add_project_alias_locked(
    project: str,
    alias: str,
    *,
    projects_root: Path | None = None,
) -> ProjectRecordWire:
    """Add *alias* to *project* while holding the ProjectSpec lock."""
    record = _add_project_alias_locked(
        project,
        alias,
        projects_root=_projects_root(projects_root),
        resolve_project_ref=resolve_project_alias_ref,
        list_project_records=list_project_records,
        apply_project_aliases_update=apply_project_aliases_update,
    )
    _invalidate_xprompt_project_identity()
    return record


def remove_project_alias_locked(
    project: str,
    alias: str,
    *,
    projects_root: Path | None = None,
) -> ProjectRecordWire:
    """Remove *alias* from *project* while holding the ProjectSpec lock."""
    record = _remove_project_alias_locked(
        project,
        alias,
        projects_root=_projects_root(projects_root),
        resolve_project_ref=resolve_project_alias_ref,
        list_project_records=list_project_records,
        apply_project_aliases_update=apply_project_aliases_update,
    )
    _invalidate_xprompt_project_identity()
    return record


def clear_project_aliases_locked(
    project: str,
    *,
    projects_root: Path | None = None,
) -> ProjectRecordWire:
    """Remove all aliases from *project* while holding the ProjectSpec lock."""
    return set_project_aliases_locked(project, [], projects_root=projects_root)


def _set_project_name_locked(
    project: str,
    name: str | None,
    *,
    projects_root: Path | None = None,
    commit_msg: str = "Set project name",
    preserve_existing: bool = False,
) -> ProjectRecordWire:
    """Replace ``PROJECT_NAME`` while holding the ProjectSpec lock."""
    root = _projects_root(projects_root)
    record = _set_project_name_locked_impl(
        project,
        name,
        projects_root=root,
        commit_msg=commit_msg,
        preserve_existing=preserve_existing,
        resolve_project_ref=resolve_project_alias_ref,
        list_project_records=list_project_records,
        apply_project_name_update=apply_project_name_update,
    )
    from sase.project_display_names import invalidate_project_display_snapshot

    invalidate_project_display_snapshot(root)
    return record


# symvision: https://github.com/sase-org/sase-github.git
def ensure_project_name_locked(
    project: str,
    name: str,
    *,
    projects_root: Path | None = None,
) -> ProjectRecordWire:
    """Ensure ``PROJECT_NAME`` is set to *name* while holding its spec lock."""
    return _set_project_name_locked(
        project,
        name,
        commit_msg=f"Ensure project name {name}",
        preserve_existing=True,
        projects_root=projects_root,
    )


def load_project_alias_map(projects_root: Path | str | None = None) -> dict[str, str]:
    """Return ``alias -> canonical project`` for all non-system projects.

    Conflicting refs are dropped deterministically instead of guessed, while
    mutation paths continue to reject conflicts strictly.
    """
    return project_alias_map_from_records(
        _filtered_project_records(projects_root),
        strict=False,
    )


def resolve_project_alias_ref(
    ref: str,
    projects_root: Path | str | None = None,
) -> str:
    """Return the canonical project name for an exact alias ref."""
    return load_project_alias_map(projects_root).get(ref, ref)


def find_project_ref_owner(
    ref: str,
    projects_root: Path | str | None = None,
) -> str | None:
    """Return the project claiming *ref* as PROJECT_NAME or alias, if any."""
    for record in _filtered_project_records(projects_root):
        if record.project_name == ref:
            continue
        if ref == normalize_project_name(record.display_name):
            return record.project_name
        if ref in normalize_project_aliases(record.aliases):
            return record.project_name
    return None


def _load_project_changespec_names(project: str) -> frozenset[str]:
    """Return active and archived Patch names for *project*."""
    from sase.ace.patch import parse_project_file
    from sase.ace.patch.project_spec_path import preferred_project_spec_path

    project_dir = sase_projects_dir() / project
    names: set[str] = set()
    for archive in (False, True):
        project_file = Path(
            preferred_project_spec_path(
                str(project_dir),
                project,
                archive=archive,
            )
        )
        if project_file.is_file():
            names.update(patch.name for patch in parse_project_file(str(project_file)))
    return frozenset(names)


def _project_workflow_type(project: str) -> str | None:
    """Return the detected VCS workflow type for *project*, if resolvable.

    Offline-safe: returns ``None`` when the project has no spec file yet or
    no plugin claims it, so canonicalization degrades to today's
    alias-only behavior instead of raising mid-rewrite.
    """
    from sase.ace.patch.project_spec_path import preferred_project_spec_path
    from sase.workspace_provider import detect_workflow_type

    project_dir = sase_projects_dir() / project
    project_file = Path(preferred_project_spec_path(str(project_dir), project))
    if not project_file.is_file():
        return None
    try:
        return detect_workflow_type(str(project_file))
    except ValueError:
        return None


def canonicalize_project_aliases_in_prompt(prompt: str) -> str:
    """Rewrite project alias refs in VCS launch tags to canonical names."""
    if "#" not in prompt:
        return prompt
    pattern = _project_alias_ref_pattern()
    if pattern is None:
        return prompt
    from sase.project_alias_prompts import (
        canonicalize_project_aliases_in_prompt as _canonicalize_prompt,
    )

    return _canonicalize_prompt(
        prompt,
        pattern=pattern,
        load_alias_map=load_project_alias_map,
        load_changespec_names=_load_project_changespec_names,
        project_workflow_type=_project_workflow_type,
    )


def humanize_project_refs_in_prompt(
    prompt: str,
    display_name_by_project: Mapping[str, str],
) -> str:
    """Rewrite canonical project refs in VCS launch tags to display names."""
    if "#" not in prompt or not display_name_by_project:
        return prompt
    pattern = _project_alias_ref_pattern()
    if pattern is None:
        return prompt
    from sase.project_alias_prompts import (
        humanize_project_refs_in_prompt as _humanize_prompt,
    )

    return _humanize_prompt(
        prompt,
        display_name_by_project,
        pattern=pattern,
    )


__all__ = [
    "ProjectAliasError",
    "add_project_alias_locked",
    "allocate_project_name",
    "canonicalize_project_aliases_in_prompt",
    "clear_project_aliases_locked",
    "ensure_project_name_locked",
    "effective_project_name",
    "find_project_ref_owner",
    "humanize_project_refs_in_prompt",
    "load_project_alias_map",
    "remove_project_alias_locked",
    "resolve_project_alias_ref",
    "set_project_aliases_locked",
]
