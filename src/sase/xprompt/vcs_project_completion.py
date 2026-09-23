"""Headless foundations for the ``+`` project/patch-completion feature.

This module provides the pure-logic building blocks shared by the TUI prompt
input widget (consuming the catalog directly) and the Rust xprompt LSP
(consuming a materialized JSON catalog built from
:func:`build_vcs_project_completion_entries`).

The public helpers are:

* :func:`build_vcs_project_completion_entries` -- the enabled project/patch catalog.
* :func:`filter_vcs_project_entries` -- case-insensitive prefix filtering.
* :class:`VcsProjectTrigger` -- the trigger value type shared with the
  core-backed :func:`sase.project_tags.find_project_tag_trigger`.

Trigger detection and the in-place accept algorithm live in the Rust core
(``project_tag_trigger`` / ``project_tag_apply_selection``); the Python
mirrors were deleted once the core owned them (project tags epic,
tui-editor phase). The golden vectors live in the core's
``project_tag/tests.rs``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from sase.ace.patch import (
    Patch as Patch,
    iter_patch_project_files,
    parse_project_file,
)
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.project_display_names import ProjectDisplaySnapshot, humanize_cl_name
from sase.project_tags.catalog import build_targets, load_project_tag_catalog
from sase.status_state_machine import remove_workspace_suffix
from sase.workspace_provider import (
    detect_workflow_type,
    get_display_name,
    get_workflow_names,
)

# The system-managed project that must never appear as a completion candidate.
_HOME_PROJECT_NAME = "home"

_ACTIVE_PATCH_STATUSES = frozenset({"WIP", "Draft", "Ready", "Mailed"})

# Schema version for the materialized JSON catalog handed to the Rust LSP. Bump
# when the on-disk shape changes; the Rust loader tolerates unknown extra keys.
VCS_PROJECT_CATALOG_SCHEMA_VERSION = 5

VcsProjectEntryKind = Literal["project", "patch", "changespec"]  # legacy catalog kind


def _canonical_vcs_project_entry_kind(kind: str) -> str:
    """Return the canonical entry discriminator for current in-process code."""
    return "patch" if kind in {"patch", "changespec"} else kind  # legacy catalog kind


def _legacy_vcs_project_entry_kind(kind: str) -> str:
    """Return the legacy discriminator used by old catalog consumers."""
    return "changespec" if _canonical_vcs_project_entry_kind(kind) == "patch" else kind


@dataclass(frozen=True)
class VcsProjectEntry:
    """One enabled project or patch completion candidate.

    Attributes:
        name: Project name (e.g. ``"sase"``) or patch name.
        vcs_prefix: VCS workflow prefix (e.g. ``"gh"``, ``"git"``).
        display_tag: The resulting VCS workflow tag, without a trailing space
            (e.g. ``"#gh:sase"``).
        provider_display: Human-readable provider name (e.g. ``"GitHub"``),
            falling back to ``vcs_prefix`` when no display name is registered.
        description: Project description, when available (empty otherwise).
        aliases: Alternate names the project can be matched by. Patches do
            not currently carry aliases.
        kind: ``"project"`` for project rows, ``"patch"`` for patch rows.
        project: Owning project basename. For project rows, this equals
            ``name``.
        status: Base patch status for patch rows; empty for project rows.
        key: Directory key (e.g. ``"gh_sase-org__sase"``). Present in v5+
            catalogs; empty for patch rows.
        tag: Project tag spelling (e.g. ``"+sase"``), or empty when the name
            is not in the tag grammar. Present in v5+ catalogs.
        accent_index: Index into the catalog's ``accent_palette``. Present in
            v5+ catalogs; ``None`` for rows without an accent.
        current: Whether this row is the current project. Present in v5+
            catalogs; ``None`` for patch rows.
    """

    name: str
    vcs_prefix: str
    display_tag: str
    provider_display: str
    description: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    kind: VcsProjectEntryKind = "project"
    project: str = ""
    status: str = ""
    key: str = ""
    tag: str = ""
    accent_index: int | None = None
    current: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _canonical_vcs_project_entry_kind(self.kind),
        )


@dataclass(frozen=True)
class VcsProjectTrigger:
    """A detected ``+query`` completion trigger token.

    Attributes:
        start: Index of the leading ``+`` within the prompt.
        end: Index one past the end of the trigger token (the next whitespace
            boundary or end of prompt).
        query: The filter text after the ``+`` prefix up to the cursor (empty
            for a bare ``+``).
    """

    start: int
    end: int
    query: str

    @property
    def span(self) -> tuple[int, int]:
        """Return the ``(start, end)`` span of the trigger token."""
        return (self.start, self.end)


# --- Catalog ---------------------------------------------------------------

# Module-level cache: (signature, entries). Invalidated by ProjectSpec file
# mtimes so both project membership and patch edits are picked up, and
# explicitly clearable via :func:`_clear_vcs_project_completion_cache`.
_ENTRIES_CACHE: tuple[object, tuple[VcsProjectEntry, ...]] | None = None


def _catalog_signature(projects_dir: Path) -> object | None:
    """Return a cheap cache signature for *projects_dir*, or ``None``.

    The catalog now includes patches, so a top-level projects-directory
    ``stat`` would miss status/name edits inside ProjectSpec files. Use the
    lifecycle-selected ProjectSpec files themselves as the cache key.
    """
    try:
        project_files = iter_patch_project_files(
            projects_dir=projects_dir,
            include_states=("enabled",),
            include_home=False,
        )
    except OSError:
        return None

    file_signatures: list[tuple[str, int, int]] = []
    for project_file in project_files:
        try:
            stat = project_file.stat()
        except OSError:
            continue
        file_signatures.append((str(project_file), stat.st_mtime_ns, stat.st_size))
    return (str(projects_dir), tuple(sorted(file_signatures)))


def vcs_project_catalog_signature(projects_dir: Path) -> object | None:
    """Return the cache signature used by the VCS project catalog."""
    return _catalog_signature(projects_dir)


def _iter_enabled_project_patches(projects_dir: Path) -> Iterator[Patch]:
    """Yield patches from enabled projects' ProjectSpec files."""
    for project_file in iter_patch_project_files(
        projects_dir=projects_dir,
        include_states=("enabled",),
        include_home=False,
    ):
        yield from parse_project_file(str(project_file))


def _current_catalog_key() -> str | None:
    """Return the current project's directory key, or ``None``.

    Degrades to ``None`` when the MRU cannot be read; ordering then falls
    back to MRU recency and name.
    """

    try:
        from sase.current_project import resolve_current_project

        current = resolve_current_project()
    except Exception:  # noqa: BLE001 - ordering degrades to MRU/name.
        return None
    return current.project_key if current is not None else None


def _mru_catalog_rank() -> dict[str, int]:
    """Return a directory-key/name MRU recency rank (lower is more recent)."""

    try:
        from sase.history.vcs_xprompt_mru import (
            load_launchable_vcs_xprompt_mru_pairs,
        )

        pairs = load_launchable_vcs_xprompt_mru_pairs(prune=False)
    except Exception:  # noqa: BLE001 - ordering degrades to name.
        return {}
    rank: dict[str, int] = {}
    for index, (canonical, display) in enumerate(pairs):
        ref = canonical.split(":", 1)[1] if ":" in canonical else canonical
        rank.setdefault(ref, index)
        rank.setdefault(display, index)
    return rank


def _build_entries(projects_dir: Path) -> list[VcsProjectEntry]:
    """Build the enabled project/patch completion catalog from *projects_dir*.

    Project rows derive from the shared project-tag catalog
    (:func:`build_targets`), so there is one source for tag resolution and
    completion. Rows are ordered current-project-first, then MRU recency,
    then name; patch rows follow. ``home`` is never offered as a row.
    """
    project_entries: dict[str, VcsProjectEntry] = {}
    prefix_by_project: dict[str, tuple[str, str]] = {}
    records = list_project_records(projects_dir, "enabled")
    project_display_snapshot = ProjectDisplaySnapshot.from_records(records)
    targets = build_targets(
        records,
        detect_workflow_type=detect_workflow_type,
        get_display_name=get_display_name,
    )
    current_key = _current_catalog_key()
    for target in targets:
        if target.state != "enabled" or not target.launchable:
            continue
        if target.key == _HOME_PROJECT_NAME:
            continue
        if target.workflow_type is None:
            # No workspace plugin claims this project (e.g. its provider
            # plugin is not installed); it cannot expand into a VCS tag.
            continue
        vcs_prefix = target.workflow_type
        display_name = target.name
        aliases = tuple(target.aliases)
        if display_name != target.key:
            aliases = (*aliases, target.key)
        # Dedupe by storage project name (last record wins).
        project_entries[target.key] = VcsProjectEntry(
            name=display_name,
            vcs_prefix=vcs_prefix,
            display_tag=f"#{vcs_prefix}:{display_name}",
            provider_display=target.provider_display,
            description="",
            aliases=aliases,
            kind="project",
            project=target.key,
            status="",
            key=target.key,
            tag=target.tag or "",
            accent_index=target.accent_index,
            current=(target.key == current_key),
        )
        prefix_by_project[target.key] = (vcs_prefix, target.provider_display)

    patch_entries: list[VcsProjectEntry] = []
    for patch in _iter_enabled_project_patches(projects_dir):
        base_status = remove_workspace_suffix(patch.status)
        if base_status not in _ACTIVE_PATCH_STATUSES:
            continue
        project = patch.project_basename
        prefix_info = prefix_by_project.get(project)
        if prefix_info is None:
            continue
        vcs_prefix, provider_display = prefix_info
        display_name = humanize_cl_name(
            patch.name,
            snapshot=project_display_snapshot,
        )
        aliases = (patch.name,) if display_name != patch.name else ()
        patch_entries.append(
            VcsProjectEntry(
                name=display_name,
                vcs_prefix=vcs_prefix,
                display_tag=f"#{vcs_prefix}:{display_name}",
                provider_display=provider_display,
                description="",
                aliases=aliases,
                kind="patch",
                project=project,
                status=base_status,
            )
        )

    # D7 row order: the current project first, then MRU recency, then
    # alphabetical. Patch rows follow, grouped by owning project and name.
    mru_rank = _mru_catalog_rank()
    fallback_rank = len(mru_rank) + 1

    def _project_sort_key(entry: VcsProjectEntry) -> tuple[int, int, str]:
        current = 0 if entry.current else 1
        recency = mru_rank.get(entry.key, fallback_rank)
        if entry.key not in mru_rank:
            recency = mru_rank.get(entry.name, fallback_rank)
        return (current, recency, entry.name.casefold())

    return [
        *sorted(project_entries.values(), key=_project_sort_key),
        *sorted(patch_entries, key=lambda entry: (entry.project, entry.name)),
    ]


def build_vcs_project_completion_entries(
    projects_dir: Path | str | None = None,
    *,
    use_cache: bool = True,
) -> list[VcsProjectEntry]:
    """Return ordered completion entries for launchable enabled projects and patches.

    Records that are system-managed, non-launchable, or whose workflow type
    cannot be detected are excluded. Project rows are deduped by name and sorted
    by name; active patch rows follow, grouped by owning project and name.

    Args:
        projects_dir: Projects root to enumerate. Defaults to the SASE projects
            directory.
        use_cache: When ``True`` (default), reuse a cached catalog while the
            projects directory is unchanged. Pass ``False`` to force a rebuild.

    Returns:
        A fresh list of :class:`VcsProjectEntry`.
    """
    global _ENTRIES_CACHE  # noqa: PLW0603

    resolved = Path(projects_dir) if projects_dir is not None else sase_projects_dir()
    signature = _catalog_signature(resolved)

    if use_cache and signature is not None and _ENTRIES_CACHE is not None:
        cached_signature, cached_entries = _ENTRIES_CACHE
        if cached_signature == signature:
            return list(cached_entries)

    entries = _build_entries(resolved)

    if use_cache and signature is not None:
        _ENTRIES_CACHE = (signature, tuple(entries))

    return entries


def _clear_vcs_project_completion_cache() -> None:
    """Drop the cached project/patch-completion catalog.

    Test-only helper for resetting the module-level cache between cases; the
    cache is otherwise invalidated automatically by the projects directory
    mtime (see :func:`_catalog_signature`).
    """
    global _ENTRIES_CACHE  # noqa: PLW0603
    _ENTRIES_CACHE = None


def vcs_project_catalog_payload(
    projects_dir: Path | str | None = None,
) -> dict[str, object]:
    """Return the JSON-serializable ``vcs_project`` completion catalog.

    Bundles the enabled-project entries (from
    :func:`build_vcs_project_completion_entries`) with the full set of known VCS
    workflow names and optional ref-root namespaces. The names let the
    out-of-process Rust LSP replace *any*
    existing workflow tag in a prompt (e.g. ``#git:foo``), not just those of
    enabled projects, keeping its expansion byte-identical to the Python/TUI
    side. This is the on-disk contract consumed by ``sase-xprompt-lsp``,
    materialized at LSP launch by :mod:`sase.integrations.xprompt_lsp`.

    The v5 shape adds ``accent_palette`` (the Python-owned 18-color palette),
    ``project_tags`` (every tag-resolution target), and per-entry ``key``,
    ``tag``, ``accent_index``, and ``current`` fields. Entries are ordered
    current-project-first, then MRU recency, then name; patch rows last.

    Args:
        projects_dir: Projects root to enumerate. Defaults to the SASE projects
            directory.

    Returns:
        A mapping with ``schema_version``, sorted ``workflow_names``, the
        ordered ``entries`` list (each a plain dict mirroring
        :class:`VcsProjectEntry`), and ``namespaces`` keyed by workflow.
    """
    entries = build_vcs_project_completion_entries(projects_dir)
    workflow_names = sorted(get_workflow_names())

    from sase.project_accents import PROJECT_ACCENTS
    from sase.xprompt.vcs_ref_completion import vcs_ref_namespaces_by_workflow

    namespaces_by_workflow = vcs_ref_namespaces_by_workflow(
        workflow_names,
        projects_dir,
    )
    try:
        tag_catalog = load_project_tag_catalog(projects_dir)
    except Exception:  # noqa: BLE001 - catalog extras degrade to empty.
        tag_catalog = None
    serialized_entries: list[dict[str, object]] = []
    for entry in entries:
        entry_kind = _canonical_vcs_project_entry_kind(entry.kind)
        serialized_entry: dict[str, object] = {
            "name": entry.name,
            "vcs_prefix": entry.vcs_prefix,
            "display_tag": entry.display_tag,
            "provider_display": entry.provider_display,
            "description": entry.description,
            "aliases": list(entry.aliases),
            # Legacy readers only understand `changespec` for patch rows.
            "kind": _legacy_vcs_project_entry_kind(entry_kind),
            "project": entry.project,
            "status": entry.status,
            # v5 additions: directory key, tag spelling, accent palette
            # index, and whether this row is the current project.
            "key": entry.key,
            "tag": entry.tag,
            "accent_index": entry.accent_index,
            "current": entry.current,
        }
        if entry_kind != "project":
            serialized_entry["entry_kind"] = entry_kind
        serialized_entries.append(serialized_entry)

    return {
        "schema_version": VCS_PROJECT_CATALOG_SCHEMA_VERSION,
        "workflow_names": workflow_names,
        "entries": serialized_entries,
        "namespaces": {
            workflow: [
                {
                    "name": entry.name,
                    "description": entry.description,
                    "kind_label": entry.kind_label,
                }
                for entry in entries
            ]
            for workflow, entries in namespaces_by_workflow.items()
        },
        "accent_palette": (
            list(tag_catalog.accent_palette)
            if tag_catalog is not None
            else list(PROJECT_ACCENTS)
        ),
        "project_tags": (tag_catalog.wire_targets() if tag_catalog is not None else []),
    }


def filter_vcs_project_entries(
    entries: list[VcsProjectEntry],
    query: str,
) -> list[VcsProjectEntry]:
    """Return *entries* whose name or an alias prefix-matches *query*.

    Matching is case-insensitive. An empty *query* returns all entries. Input
    order (name-sorted, from the builder) is preserved.
    """
    needle = query.lower()
    if not needle:
        return list(entries)
    return [
        entry
        for entry in entries
        if entry.name.lower().startswith(needle)
        or any(alias.lower().startswith(needle) for alias in entry.aliases)
    ]


__all__ = [
    "VCS_PROJECT_CATALOG_SCHEMA_VERSION",
    "VcsProjectEntry",
    "VcsProjectTrigger",
    "build_vcs_project_completion_entries",
    "filter_vcs_project_entries",
    "vcs_project_catalog_signature",
    "vcs_project_catalog_payload",
]
