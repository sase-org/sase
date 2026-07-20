"""Headless foundations for the ``+`` project/PR-completion feature.

This module provides the pure-logic building blocks shared by the TUI prompt
input widget (consuming these helpers directly) and the Rust xprompt LSP
(consuming a materialized JSON catalog built from
:func:`build_vcs_project_completion_entries`).

The four public helpers are:

* :func:`build_vcs_project_completion_entries` -- the enabled project/PR catalog.
* :func:`filter_vcs_project_entries` -- case-insensitive prefix filtering.
* :func:`find_vcs_project_trigger` -- detect a ``+query`` trigger token at
  prompt offset zero or immediately after a literal ASCII space.
* :func:`apply_vcs_project_selection` -- expand a selected project or PR into
  the prompt via the canonical VCS-tag expansion algorithm.

The canonical expansion algorithm implemented by
:func:`apply_vcs_project_selection` is the cross-language parity contract: the
Rust core must produce byte-identical output for the golden test vectors. Keep
both sides in sync when changing it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from sase.ace.changespec import (
    ChangeSpec,
    iter_changespec_project_files,
    parse_project_file,
)
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import effective_project_name
from sase.project_display_names import ProjectDisplaySnapshot, humanize_cl_name
from sase.status_state_machine import remove_workspace_suffix
from sase.workspace_provider import (
    detect_workflow_type,
    get_display_name,
    get_workflow_names,
)
from sase.xprompt import _parsing

# The system-managed project that must never appear as a completion candidate.
_HOME_PROJECT_NAME = "home"

_ACTIVE_CHANGESPEC_STATUSES = frozenset({"WIP", "Draft", "Ready", "Mailed"})

# Schema version for the materialized JSON catalog handed to the Rust LSP. Bump
# when the on-disk shape changes; the Rust loader tolerates unknown extra keys.
VCS_PROJECT_CATALOG_SCHEMA_VERSION = 3

VcsProjectEntryKind = Literal["project", "changespec"]


@dataclass(frozen=True)
class VcsProjectEntry:
    """One enabled project or ChangeSpec completion candidate.

    Attributes:
        name: Project name (e.g. ``"sase"``) or ChangeSpec name.
        vcs_prefix: VCS workflow prefix (e.g. ``"gh"``, ``"git"``).
        display_tag: The resulting VCS workflow tag, without a trailing space
            (e.g. ``"#gh:sase"``).
        provider_display: Human-readable provider name (e.g. ``"GitHub"``),
            falling back to ``vcs_prefix`` when no display name is registered.
        description: Project description, when available (empty otherwise).
        aliases: Alternate names the project can be matched by. ChangeSpecs do
            not currently carry aliases.
        kind: ``"project"`` for project rows, ``"changespec"`` for PR rows.
        project: Owning project basename. For project rows, this equals
            ``name``.
        status: Base ChangeSpec status for PR rows; empty for project rows.
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
# mtimes so both project membership and ChangeSpec edits are picked up, and
# explicitly clearable via :func:`_clear_vcs_project_completion_cache`.
_ENTRIES_CACHE: tuple[object, tuple[VcsProjectEntry, ...]] | None = None


def _catalog_signature(projects_dir: Path) -> object | None:
    """Return a cheap cache signature for *projects_dir*, or ``None``.

    The catalog now includes ChangeSpecs, so a top-level projects-directory
    ``stat`` would miss status/name edits inside ProjectSpec files. Use the
    lifecycle-selected ProjectSpec files themselves as the cache key.
    """
    try:
        project_files = iter_changespec_project_files(
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


def _iter_enabled_project_changespecs(projects_dir: Path) -> Iterator[ChangeSpec]:
    """Yield ChangeSpecs from enabled projects' ProjectSpec files."""
    for project_file in iter_changespec_project_files(
        projects_dir=projects_dir,
        include_states=("enabled",),
        include_home=False,
    ):
        yield from parse_project_file(str(project_file))


def _build_entries(projects_dir: Path) -> list[VcsProjectEntry]:
    """Build the enabled project/PR completion catalog from *projects_dir*."""
    project_entries: dict[str, VcsProjectEntry] = {}
    prefix_by_project: dict[str, tuple[str, str]] = {}
    records = list_project_records(projects_dir, "enabled")
    project_display_snapshot = ProjectDisplaySnapshot.from_records(records)
    for record in records:
        if record.system_managed or not record.launchable:
            continue
        if record.project_name == _HOME_PROJECT_NAME:
            continue
        try:
            vcs_prefix = detect_workflow_type(record.project_file)
        except ValueError:
            # No workspace plugin claims this project (e.g. its provider plugin
            # is not installed); it cannot be expanded into a VCS tag, so skip.
            continue
        if not vcs_prefix:
            continue
        provider_display = get_display_name(vcs_prefix) or vcs_prefix
        display_name = effective_project_name(record)
        aliases = tuple(record.aliases)
        if display_name != record.project_name:
            aliases = (*aliases, record.project_name)
        # Dedupe by storage project name (last record wins).
        project_entries[record.project_name] = VcsProjectEntry(
            name=display_name,
            vcs_prefix=vcs_prefix,
            display_tag=f"#{vcs_prefix}:{display_name}",
            provider_display=provider_display,
            description="",
            aliases=aliases,
            kind="project",
            project=record.project_name,
            status="",
        )
        prefix_by_project[record.project_name] = (vcs_prefix, provider_display)

    changespec_entries: list[VcsProjectEntry] = []
    for changespec in _iter_enabled_project_changespecs(projects_dir):
        base_status = remove_workspace_suffix(changespec.status)
        if base_status not in _ACTIVE_CHANGESPEC_STATUSES:
            continue
        project = changespec.project_basename
        prefix_info = prefix_by_project.get(project)
        if prefix_info is None:
            continue
        vcs_prefix, provider_display = prefix_info
        display_name = humanize_cl_name(
            changespec.name,
            snapshot=project_display_snapshot,
        )
        aliases = (changespec.name,) if display_name != changespec.name else ()
        changespec_entries.append(
            VcsProjectEntry(
                name=display_name,
                vcs_prefix=vcs_prefix,
                display_tag=f"#{vcs_prefix}:{display_name}",
                provider_display=provider_display,
                description="",
                aliases=aliases,
                kind="changespec",
                project=project,
                status=base_status,
            )
        )

    return [
        *sorted(project_entries.values(), key=lambda entry: entry.name),
        *sorted(changespec_entries, key=lambda entry: (entry.project, entry.name)),
    ]


def build_vcs_project_completion_entries(
    projects_dir: Path | str | None = None,
    *,
    use_cache: bool = True,
) -> list[VcsProjectEntry]:
    """Return ordered completion entries for launchable enabled projects and PRs.

    Records that are system-managed, non-launchable, or whose workflow type
    cannot be detected are excluded. Project rows are deduped by name and sorted
    by name; active ChangeSpec rows follow, grouped by owning project and name.

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
    """Drop the cached project/PR-completion catalog.

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

    from sase.xprompt.vcs_ref_completion import vcs_ref_namespaces_by_workflow

    namespaces_by_workflow = vcs_ref_namespaces_by_workflow(
        workflow_names,
        projects_dir,
    )
    return {
        "schema_version": VCS_PROJECT_CATALOG_SCHEMA_VERSION,
        "workflow_names": workflow_names,
        "entries": [
            {
                "name": entry.name,
                "vcs_prefix": entry.vcs_prefix,
                "display_tag": entry.display_tag,
                "provider_display": entry.provider_display,
                "description": entry.description,
                "aliases": list(entry.aliases),
                "kind": entry.kind,
                "project": entry.project,
                "status": entry.status,
            }
            for entry in entries
        ],
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


# --- Trigger detection -----------------------------------------------------


def find_vcs_project_trigger(prompt: str, cursor: int) -> VcsProjectTrigger | None:
    """Detect a ``+query`` trigger at *cursor* in *prompt*.

    The non-whitespace token immediately preceding *cursor* must start with
    ``+``, and that plus must be at absolute prompt offset ``0`` or immediately
    after a literal ASCII space. Newlines, tabs, other whitespace, and plus
    signs embedded in words or operators do not trigger. ``#+`` is ordinary
    prompt text for this feature.

    Args:
        prompt: The full prompt text.
        cursor: Caret index within *prompt*.

    Returns:
        A :class:`VcsProjectTrigger` describing the token span and filter query,
        or ``None`` when no trigger applies.
    """
    if cursor < 0 or cursor > len(prompt):
        return None

    # Walk back through the run of non-whitespace characters before the cursor
    # to find the token start.
    start = cursor
    while start > 0 and not prompt[start - 1].isspace():
        start -= 1

    follows_literal_space = start > 0 and prompt[start - 1] == " "
    if prompt[start : start + 1] != "+" or not (start == 0 or follows_literal_space):
        return None

    # The cursor must sit past the prefix for the trigger to be live.
    if cursor < start + 1:
        return None

    # Extend forward to the end of the token (next whitespace or end of prompt).
    end = start
    while end < len(prompt) and not prompt[end].isspace():
        end += 1

    query = prompt[start + 1 : cursor]
    return VcsProjectTrigger(start=start, end=end, query=query)


# --- Expansion (the canonical parity contract) -----------------------------


def _strip_trigger_token(prompt: str, start: int, end: int) -> str:
    """Remove the trigger span ``[start, end)`` and collapse one stray space.

    The collapse avoids leaving a double space, an orphan trailing space at the
    end of a line/prompt, or an orphan leading space at the start of a
    line/prompt.
    """
    before = prompt[:start]
    after = prompt[end:]
    before_space = before.endswith(" ")
    after_space = after.startswith(" ")

    if before_space and after_space:
        # The token sat between two spaces; collapse to a single space.
        after = after[1:]
    elif before_space and (after == "" or after[0] in "\r\n"):
        # A trailing space would be orphaned at end of line/prompt.
        before = before[:-1]
    elif after_space and (before == "" or before[-1] in "\r\n"):
        # A leading space would be orphaned at start of line/prompt.
        after = after[1:]

    return before + after


def apply_vcs_project_selection(
    prompt: str,
    trigger_span: tuple[int, int],
    display_tag: str,
) -> str:
    """Expand a selected project into *prompt*, returning the new prompt text.

    Implements the canonical expansion algorithm: remove the trigger token,
    collapse one adjacent space, then either replace every line-start VCS
    workflow tag with *display_tag* or, when none exist, prepend *display_tag*
    after any leading frontmatter / whitespace / ``%directive`` tokens.

    Args:
        prompt: The full prompt text.
        trigger_span: The ``(start, end)`` span of the ``+query`` trigger token.
        display_tag: The selected project's VCS tag, without a trailing space
            (e.g. ``"#gh:sase"``).

    Returns:
        The rewritten prompt text.
    """
    start, end = trigger_span
    base = _strip_trigger_token(prompt, start, end)

    # ``replace_vcs_workflow_tags`` replaces every line-start VCS tag, or -- when
    # none exist -- prepends the tag at offset 0. Detect that no-tag case (its
    # output is exactly the naive prepend) and redo it with frontmatter /
    # directive-aware placement.
    replaced = _parsing.replace_vcs_workflow_tags(base, display_tag)
    if replaced != f"{display_tag} {base}":
        return replaced

    offset = _parsing.find_vcs_workflow_tag_prepend_offset(base)
    return f"{base[:offset]}{display_tag} {base[offset:]}"


__all__ = [
    "VCS_PROJECT_CATALOG_SCHEMA_VERSION",
    "VcsProjectEntry",
    "VcsProjectTrigger",
    "apply_vcs_project_selection",
    "build_vcs_project_completion_entries",
    "filter_vcs_project_entries",
    "find_vcs_project_trigger",
    "vcs_project_catalog_signature",
    "vcs_project_catalog_payload",
]
