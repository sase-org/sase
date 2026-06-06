"""Project alias services and launch-boundary VCS ref canonicalization."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from sase.core.paths import is_valid_sase_project_name, sase_projects_dir
from sase.core.project_lifecycle_facade import (
    apply_project_aliases_update,
    list_project_records,
)
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_STATES,
    ProjectRecordWire,
)
from sase.xprompt._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks

_KNOWN_VCS_WORKFLOW_NAMES = frozenset({"gh", "git", "hg", "jj", "p4"})
_REF_CHARS = r"[A-Za-z0-9_.~-]+"
_REF_BOUNDARY = r"(?=$|[\s)\]},.!?;:\"'])"
_ALL_STATES = tuple(PROJECT_LIFECYCLE_STATES)


class ProjectAliasError(RuntimeError):
    """Base class for project alias service failures."""


class _ProjectAliasNotFoundError(ProjectAliasError):
    """Raised when a requested project cannot be resolved."""


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


def _candidate_prompt(prompt: str) -> tuple[str, list[str]]:
    fenced_blocks: list[str] = []
    return protect_fenced_blocks(prompt, fenced_blocks), fenced_blocks


def _filtered_project_records(
    projects_root: Path | str | None,
) -> list[ProjectRecordWire]:
    root = Path(projects_root) if projects_root is not None else sase_projects_dir()
    if not root.is_dir():
        return []
    try:
        records = list_project_records(root, "all", include_home=False)
    except (ImportError, AttributeError):
        return []
    return [
        record
        for record in records
        if record.project_name != "home" and not record.system_managed
    ]


def _normalize_project_aliases(aliases: Iterable[str]) -> list[str]:
    """Return trimmed, deduplicated project aliases in stable order."""
    return sorted({alias.strip() for alias in aliases if alias.strip()})


def _non_system_project_records(
    records: Sequence[ProjectRecordWire],
) -> list[ProjectRecordWire]:
    return [
        record
        for record in records
        if record.project_name != "home" and not record.system_managed
    ]


def _project_alias_map_from_records(
    records: Sequence[ProjectRecordWire],
    *,
    overrides: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, str]:
    project_names = {
        record.project_name for record in _non_system_project_records(records)
    }
    alias_map: dict[str, str] = {}

    for record in _non_system_project_records(records):
        aliases = (
            overrides[record.project_name]
            if overrides is not None and record.project_name in overrides
            else record.aliases
        )
        for alias in _normalize_project_aliases(aliases):
            if not is_valid_sase_project_name(alias):
                raise ValueError(
                    f"invalid project alias {alias!r} for project "
                    f"{record.project_name!r}"
                )
            if alias == record.project_name:
                raise ValueError(
                    f"project alias {alias!r} cannot equal project "
                    f"{record.project_name!r}"
                )
            if alias in project_names:
                raise ValueError(
                    f"project alias {alias!r} for project {record.project_name!r} "
                    "conflicts with a real project name"
                )
            existing = alias_map.get(alias)
            if existing is not None and existing != record.project_name:
                raise ValueError(
                    f"project alias {alias!r} is assigned to both "
                    f"{existing!r} and {record.project_name!r}"
                )
            alias_map[alias] = record.project_name

    return alias_map


def _validate_project_aliases(
    project_name: str,
    aliases: Iterable[str],
    records: Sequence[ProjectRecordWire],
) -> list[str]:
    """Validate proposed aliases for one project against project records."""
    normalized = _normalize_project_aliases(aliases)
    _project_alias_map_from_records(
        records,
        overrides={project_name: normalized},
    )
    return normalized


def allocate_project_alias(
    desired_base_alias: str,
    records: Sequence[ProjectRecordWire],
    *,
    project_name: str | None = None,
) -> str:
    """Return the first available project alias for *desired_base_alias*.

    Occupancy includes every non-system project name and every non-system
    project alias across active, inactive, and sibling records. Aliases already
    owned by *project_name* are reusable so callers can allocate idempotently
    while updating an existing project.
    """
    base = desired_base_alias.strip()
    if not is_valid_sase_project_name(base):
        raise ValueError(f"invalid project alias: {desired_base_alias!r}")

    occupied = {record.project_name for record in _non_system_project_records(records)}
    for record in _non_system_project_records(records):
        if project_name is not None and record.project_name == project_name:
            continue
        occupied.update(_normalize_project_aliases(record.aliases))

    candidate = base
    suffix = 2
    while candidate in occupied:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _get_project_record_from_records(
    records: Sequence[ProjectRecordWire],
    project: str,
) -> ProjectRecordWire:
    for record in records:
        if record.project_name == project:
            return record
    raise _ProjectAliasNotFoundError(f"project '{project}' was not found")


def _resolve_mutable_project_file(
    project: str,
    projects_root: Path | None = None,
) -> Path:
    from sase.ace.changespec.project_spec_path import preferred_project_spec_path

    if project == "home":
        raise ProjectAliasError("project 'home' is system-managed")
    if not is_valid_sase_project_name(project):
        raise ProjectAliasError(f"invalid project name: {project!r}")

    root = (
        projects_root.expanduser() if projects_root is not None else sase_projects_dir()
    )
    project_dir = root / project
    project_file = Path(preferred_project_spec_path(str(project_dir), project))
    if not project_file.is_file():
        raise _ProjectAliasNotFoundError(f"project '{project}' was not found")
    return project_file


def _reject_system_managed_record(record: ProjectRecordWire) -> None:
    if record.system_managed:
        raise ProjectAliasError(f"project '{record.project_name}' is system-managed")


def _validate_alias_arg(alias: str) -> None:
    if not is_valid_sase_project_name(alias):
        raise ProjectAliasError(f"invalid project alias: {alias!r}")


def _mutate_project_aliases_locked(
    project: str,
    update_aliases: Callable[[list[str]], list[str]],
    commit_msg: str,
    *,
    projects_root: Path | None = None,
) -> ProjectRecordWire:
    from sase.ace.changespec import changespec_lock, write_changespec_atomic

    root = (
        projects_root.expanduser() if projects_root is not None else sase_projects_dir()
    )
    project_file = _resolve_mutable_project_file(project, root)
    with changespec_lock(str(project_file)):
        records = list_project_records(
            root,
            list(_ALL_STATES),
            include_home=True,
        )
        record = _get_project_record_from_records(records, project)
        _reject_system_managed_record(record)
        aliases = _validate_project_aliases(
            record.project_name,
            update_aliases(list(record.aliases)),
            records,
        )
        content = project_file.read_text(encoding="utf-8")
        updated = apply_project_aliases_update(content, aliases)
        write_changespec_atomic(str(project_file), updated, commit_msg)

    return _get_project_record_from_records(
        list_project_records(root, list(_ALL_STATES), include_home=True),
        project,
    )


def set_project_aliases_locked(
    project: str,
    aliases: list[str],
    *,
    projects_root: Path | None = None,
) -> ProjectRecordWire:
    """Replace aliases for *project* while holding the ProjectSpec lock."""
    return _mutate_project_aliases_locked(
        project,
        lambda _current: list(aliases),
        "Set project aliases",
        projects_root=projects_root,
    )


def add_project_alias_locked(
    project: str,
    alias: str,
    *,
    projects_root: Path | None = None,
) -> ProjectRecordWire:
    """Add *alias* to *project* while holding the ProjectSpec lock."""
    _validate_alias_arg(alias)
    return _mutate_project_aliases_locked(
        project,
        lambda aliases: [*aliases, alias],
        f"Add project alias {alias}",
        projects_root=projects_root,
    )


def remove_project_alias_locked(
    project: str,
    alias: str,
    *,
    projects_root: Path | None = None,
) -> ProjectRecordWire:
    """Remove *alias* from *project* while holding the ProjectSpec lock."""
    _validate_alias_arg(alias)
    return _mutate_project_aliases_locked(
        project,
        lambda aliases: [item for item in aliases if item != alias],
        f"Remove project alias {alias}",
        projects_root=projects_root,
    )


def clear_project_aliases_locked(
    project: str,
    *,
    projects_root: Path | None = None,
) -> ProjectRecordWire:
    """Remove all aliases from *project* while holding the ProjectSpec lock."""
    return set_project_aliases_locked(project, [], projects_root=projects_root)


def ensure_project_alias_locked(
    project: str,
    alias: str,
    *,
    projects_root: Path | None = None,
) -> ProjectRecordWire:
    """Ensure *alias* is present on *project* while preserving existing aliases."""
    _validate_alias_arg(alias)
    return _mutate_project_aliases_locked(
        project,
        lambda aliases: aliases if alias in aliases else [*aliases, alias],
        f"Ensure project alias {alias}",
        projects_root=projects_root,
    )


# pyvision: sdd/epics/202606/project_aliases.md
def load_project_alias_map(projects_root: Path | str | None = None) -> dict[str, str]:
    """Return ``alias -> canonical project`` for all non-system projects.

    The map includes aliases for active, inactive, and sibling project records.
    Conflicts are rejected instead of guessed so launch-time canonicalization is
    deterministic even after manual ProjectSpec edits.
    """
    return _project_alias_map_from_records(_filtered_project_records(projects_root))


def resolve_project_alias_ref(ref: str) -> str:
    """Return the canonical project name for an exact alias ref."""
    if "/" in ref:
        return ref
    return load_project_alias_map().get(ref, ref)


def canonicalize_project_aliases_in_prompt(prompt: str) -> str:
    """Rewrite project alias refs in VCS launch tags to canonical project names."""
    if "#" not in prompt:
        return prompt

    pattern = _project_alias_ref_pattern()
    if pattern is None:
        return prompt

    protected, fenced_blocks = _candidate_prompt(prompt)
    if pattern.search(protected) is None:
        return prompt

    alias_map = load_project_alias_map()
    if not alias_map:
        return prompt

    def replace(match: re.Match[str]) -> str:
        ref = match.group("ref") or match.group("paren") or ""
        canonical = alias_map.get(ref)
        if canonical is None:
            return match.group(0)

        prefix = (
            f"{match.group('context')}#"
            f"{match.group('workflow')}{match.group('marker') or ''}"
        )
        if match.group("paren") is not None:
            return f"{prefix}({canonical})"
        return f"{prefix}:{canonical}"

    canonicalized = pattern.sub(replace, protected)
    return unprotect_fenced_blocks(canonicalized, fenced_blocks)


__all__ = [
    "ProjectAliasError",
    "add_project_alias_locked",
    "allocate_project_alias",
    "canonicalize_project_aliases_in_prompt",
    "clear_project_aliases_locked",
    "ensure_project_alias_locked",
    "load_project_alias_map",
    "remove_project_alias_locked",
    "resolve_project_alias_ref",
    "set_project_aliases_locked",
]
