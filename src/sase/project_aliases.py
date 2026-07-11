"""Project alias services and launch-boundary VCS ref canonicalization."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from sase.core.paths import is_valid_sase_project_name, sase_projects_dir
from sase.core.project_lifecycle_facade import (
    apply_project_aliases_update,
    apply_project_name_update,
    list_project_records,
)
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_STATES,
    ProjectRecordWire,
    effective_project_name,
)
from sase.xprompt._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks

logger = logging.getLogger(__name__)

_KNOWN_VCS_WORKFLOW_NAMES = frozenset({"gh", "git", "jj", "p4"})
_REF_CHARS = r"[A-Za-z0-9_./~-]+"
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


def _normalize_project_name(name: str | None) -> str | None:
    """Return a trimmed display name, or ``None`` when blank/unset."""
    if name is None:
        return None
    value = name.strip()
    return value or None


def _non_system_project_records(
    records: Sequence[ProjectRecordWire],
) -> list[ProjectRecordWire]:
    return [
        record
        for record in records
        if record.project_name != "home" and not record.system_managed
    ]


def _project_record_has_spec(record: ProjectRecordWire) -> bool:
    return Path(record.project_file).is_file() or record.archive_file is not None


def _spec_backed_project_records(
    records: Sequence[ProjectRecordWire],
) -> list[ProjectRecordWire]:
    return [
        record
        for record in _non_system_project_records(records)
        if _project_record_has_spec(record)
    ]


def _project_alias_map_from_records(
    records: Sequence[ProjectRecordWire],
    *,
    overrides: Mapping[str, Sequence[str]] | None = None,
    display_name_overrides: Mapping[str, str | None] | None = None,
    strict: bool = True,
) -> dict[str, str]:
    """Build ``ref -> canonical project`` from *records*.

    With ``strict=True`` (validation/mutation paths) any conflicting ref
    raises ``ValueError``. With ``strict=False`` (read/launch paths) a
    conflicting ref is dropped deterministically instead of crashing the
    caller: a ref shadowed by a real project name self-resolves to that
    project, and a ref claimed by two different projects resolves to
    neither. A stale conflict on disk must never brick ``sase ace``.
    """
    spec_backed_records = _spec_backed_project_records(records)
    project_names = {record.project_name for record in spec_backed_records}
    alias_map: dict[str, str] = {}
    ref_kinds: dict[tuple[str, str], str] = {}

    def _add_ref(ref: str, project_name: str, kind: str) -> None:
        if not is_valid_sase_project_name(ref):
            raise ValueError(f"invalid {kind} {ref!r} for project {project_name!r}")
        if ref == project_name:
            if kind == "PROJECT_NAME":
                return
            raise ValueError(
                f"project alias {ref!r} cannot equal project {project_name!r}"
            )
        if ref in project_names:
            if kind == "PROJECT_NAME":
                raise ValueError(
                    f"PROJECT_NAME {ref!r} for project {project_name!r} "
                    "conflicts with a real project name"
                )
            raise ValueError(
                f"project alias {ref!r} for project {project_name!r} "
                "conflicts with a real project name"
            )
        existing = alias_map.get(ref)
        if existing is not None and existing != project_name:
            raise ValueError(
                f"project reference {ref!r} is assigned to both "
                f"{existing!r} and {project_name!r}"
            )
        if existing == project_name:
            existing_kind = ref_kinds.get((project_name, ref), "project reference")
            if existing_kind != kind:
                raise ValueError(
                    f"{kind} {ref!r} for project {project_name!r} conflicts "
                    f"with {existing_kind}"
                )
            return
        alias_map[ref] = project_name
        ref_kinds[(project_name, ref)] = kind

    dropped_refs: set[str] = set()

    def add_ref(ref: str, project_name: str, kind: str) -> None:
        if not strict and ref in dropped_refs:
            logger.warning(
                "Ignoring conflicting %s %r for project %r",
                kind,
                ref,
                project_name,
            )
            return
        try:
            _add_ref(ref, project_name, kind)
        except ValueError:
            if strict:
                raise
            existing = alias_map.get(ref)
            if existing is not None and existing != project_name:
                # Claimed by two different projects: refuse to map at all so
                # the ref deterministically self-resolves.
                del alias_map[ref]
                dropped_refs.add(ref)
            logger.warning(
                "Ignoring conflicting %s %r for project %r",
                kind,
                ref,
                project_name,
            )

    for record in spec_backed_records:
        display_name = (
            _normalize_project_name(display_name_overrides[record.project_name])
            if display_name_overrides is not None
            and record.project_name in display_name_overrides
            else record.display_name
        )
        if display_name is not None:
            add_ref(display_name, record.project_name, "PROJECT_NAME")

        aliases = (
            overrides[record.project_name]
            if overrides is not None and record.project_name in overrides
            else record.aliases
        )
        for alias in _normalize_project_aliases(aliases):
            add_ref(alias, record.project_name, "project alias")

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


def _validate_project_name(
    project_name: str,
    name: str | None,
    records: Sequence[ProjectRecordWire],
) -> str | None:
    """Validate a proposed ``PROJECT_NAME`` for one project."""
    normalized = _normalize_project_name(name)
    if normalized is not None and not is_valid_sase_project_name(normalized):
        raise ValueError(f"invalid project name: {name!r}")
    _project_alias_map_from_records(
        records,
        display_name_overrides={project_name: normalized},
    )
    return normalized


def _occupied_project_refs(
    records: Sequence[ProjectRecordWire],
    *,
    project_name: str | None = None,
    include_current_aliases: bool = True,
    include_current_display_name: bool = True,
) -> set[str]:
    occupied = {record.project_name for record in _non_system_project_records(records)}
    for record in _non_system_project_records(records):
        is_current = project_name is not None and record.project_name == project_name
        if not is_current or include_current_aliases:
            occupied.update(_normalize_project_aliases(record.aliases))
        if not is_current or include_current_display_name:
            if record.display_name:
                occupied.add(record.display_name)
    return occupied


# pyvision: https://github.com/sase-org/sase-github.git
def allocate_project_name(
    desired_base_name: str,
    records: Sequence[ProjectRecordWire],
    *,
    project_name: str | None = None,
) -> str:
    """Return the first available logical project name for *desired_base_name*.

    Occupancy includes directory keys, aliases, and ``PROJECT_NAME`` values.
    Suffix allocation uses ``_<N>`` starting at ``_1``.
    """
    base = desired_base_name.strip()
    if not is_valid_sase_project_name(base):
        raise ValueError(f"invalid project name: {desired_base_name!r}")

    occupied = _occupied_project_refs(
        records,
        project_name=project_name,
        include_current_aliases=True,
        include_current_display_name=False,
    )

    candidate = base
    suffix = 1
    while candidate in occupied:
        candidate = f"{base}_{suffix}"
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
    project = resolve_project_alias_ref(project, root)
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
    project = resolve_project_alias_ref(project, root)
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


def _mutate_project_name_locked(
    project: str,
    update_name: Callable[[str | None], str | None],
    commit_msg: str,
    *,
    projects_root: Path | None = None,
) -> ProjectRecordWire:
    from sase.ace.changespec import changespec_lock, write_changespec_atomic

    root = (
        projects_root.expanduser() if projects_root is not None else sase_projects_dir()
    )
    project = resolve_project_alias_ref(project, root)
    project_file = _resolve_mutable_project_file(project, root)
    with changespec_lock(str(project_file)):
        records = list_project_records(
            root,
            list(_ALL_STATES),
            include_home=True,
        )
        record = _get_project_record_from_records(records, project)
        _reject_system_managed_record(record)
        name = _validate_project_name(
            record.project_name,
            update_name(record.display_name),
            records,
        )
        content = project_file.read_text(encoding="utf-8")
        updated = apply_project_name_update(content, name)
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


def _set_project_name_locked(
    project: str,
    name: str | None,
    *,
    projects_root: Path | None = None,
    commit_msg: str = "Set project name",
    preserve_existing: bool = False,
) -> ProjectRecordWire:
    """Replace ``PROJECT_NAME`` for *project* while holding the ProjectSpec lock."""
    normalized = _normalize_project_name(name)
    return _mutate_project_name_locked(
        project,
        lambda current: (
            current if preserve_existing and current == normalized else name
        ),
        commit_msg,
        projects_root=projects_root,
    )


# pyvision: https://github.com/sase-org/sase-github.git
def ensure_project_name_locked(
    project: str,
    name: str,
    *,
    projects_root: Path | None = None,
) -> ProjectRecordWire:
    """Ensure ``PROJECT_NAME`` is set to *name* while holding the ProjectSpec lock."""
    return _set_project_name_locked(
        project,
        name,
        commit_msg=f"Ensure project name {name}",
        preserve_existing=True,
        projects_root=projects_root,
    )


def load_project_alias_map(projects_root: Path | str | None = None) -> dict[str, str]:
    """Return ``alias -> canonical project`` for all non-system projects.

    The map includes aliases for active, inactive, and sibling project records.
    Conflicting refs are dropped deterministically instead of guessed (a ref
    shadowed by a real project name self-resolves; a ref claimed by two
    projects maps to neither) so a stale conflict on disk never crashes read
    paths such as ``sase ace`` startup. Alias/PROJECT_NAME mutations still
    reject conflicts via the strict validation helpers.
    """
    return _project_alias_map_from_records(
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
    """Return the project claiming *ref* as PROJECT_NAME or alias, if any.

    Unlike :func:`load_project_alias_map`, this reports the claim even when a
    real project named *ref* already shadows it, so creation paths can refuse
    to mint a project whose directory key would collide with another
    project's refs.
    """
    for record in _filtered_project_records(projects_root):
        if record.project_name == ref:
            continue
        if ref == _normalize_project_name(record.display_name):
            return record.project_name
        if ref in _normalize_project_aliases(record.aliases):
            return record.project_name
    return None


def _load_project_changespec_names(project: str) -> frozenset[str]:
    """Return active and archived ChangeSpec names for *project*."""
    from sase.ace.changespec import parse_project_file
    from sase.ace.changespec.project_spec_path import preferred_project_spec_path

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
            names.update(
                changespec.name for changespec in parse_project_file(str(project_file))
            )
    return frozenset(names)


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

    changespec_names_by_project: dict[str, frozenset[str]] = {}

    def changespec_names(project: str) -> frozenset[str]:
        names = changespec_names_by_project.get(project)
        if names is None:
            names = _load_project_changespec_names(project)
            changespec_names_by_project[project] = names
        return names

    aliases_by_project: dict[str, list[str]] = {}
    for alias, project in alias_map.items():
        aliases_by_project.setdefault(project, []).append(alias)
    for aliases in aliases_by_project.values():
        aliases.sort(key=lambda item: (-len(item), item))

    canonical_projects = sorted(
        aliases_by_project,
        key=lambda item: (-len(item), item),
    )

    def repair_mangled_ref(ref: str) -> str | None:
        for project in canonical_projects:
            prefix = f"{project}_"
            if not ref.startswith(prefix):
                continue

            suffix = ref[len(prefix) :]
            names = changespec_names(project)
            if ref in names or suffix in names:
                return None

            for alias in aliases_by_project[project]:
                candidate = f"{alias}_{suffix}"
                if candidate in names:
                    return candidate
        return None

    def replace(match: re.Match[str]) -> str:
        ref = match.group("ref") or match.group("paren") or ""
        canonical = alias_map.get(ref)
        if canonical is None:
            canonical = repair_mangled_ref(ref)
        if canonical is None:
            canonical = _rewrite_ref_with_known_prefix(
                ref,
                alias_map,
                allow_prefix_rewrite=lambda original_ref, project: (
                    original_ref not in changespec_names(project)
                ),
            )
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


def _rewrite_ref_with_known_prefix(
    ref: str,
    replacement_by_ref: Mapping[str, str],
    *,
    allow_prefix_rewrite: Callable[[str, str], bool] | None = None,
) -> str | None:
    replacement = replacement_by_ref.get(ref)
    if replacement is not None:
        return replacement
    if "_" not in ref:
        return None
    for known_ref, known_replacement in sorted(
        replacement_by_ref.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        prefix = f"{known_ref}_"
        if ref.startswith(prefix):
            if allow_prefix_rewrite is not None and not allow_prefix_rewrite(
                ref, known_replacement
            ):
                return None
            return f"{known_replacement}_{ref[len(prefix) :]}"
    return None


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

    protected, fenced_blocks = _candidate_prompt(prompt)
    if pattern.search(protected) is None:
        return prompt

    def replace(match: re.Match[str]) -> str:
        ref = match.group("ref") or match.group("paren") or ""
        display_name = _rewrite_ref_with_known_prefix(ref, display_name_by_project)
        if not display_name or display_name == ref:
            return match.group(0)

        prefix = (
            f"{match.group('context')}#"
            f"{match.group('workflow')}{match.group('marker') or ''}"
        )
        if match.group("paren") is not None:
            return f"{prefix}({display_name})"
        return f"{prefix}:{display_name}"

    humanized = pattern.sub(replace, protected)
    return unprotect_fenced_blocks(humanized, fenced_blocks)


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
