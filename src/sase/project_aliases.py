"""Project alias canonicalization for launch-boundary VCS refs."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from sase.core.paths import is_valid_sase_project_name, sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.xprompt._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks

_KNOWN_VCS_WORKFLOW_NAMES = frozenset({"gh", "git", "hg", "jj", "p4"})
_REF_CHARS = r"[A-Za-z0-9_.~-]+"
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


def _project_alias_map_from_records(
    records: Sequence[ProjectRecordWire],
    *,
    overrides: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, str]:
    project_names = {
        record.project_name
        for record in records
        if record.project_name != "home" and not record.system_managed
    }
    alias_map: dict[str, str] = {}

    for record in records:
        if record.project_name == "home" or record.system_managed:
            continue
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


def validate_project_aliases(
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
    "canonicalize_project_aliases_in_prompt",
    "load_project_alias_map",
    "resolve_project_alias_ref",
    "validate_project_aliases",
]
