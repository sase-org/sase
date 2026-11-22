"""Immutable project identity-to-display projection helpers.

Storage and query layers provide canonical project keys. Human-facing renderers
consume labels from a preloaded :class:`ProjectDisplaySnapshot` and retain the
paired key for interactions, joins, persistence, and structured output.

A project's human-facing name is ``effective_project_name(record)``: ``PROJECT_NAME``
when set. The directory key and the ``*.sase`` filename are storage identity and are
never used as a project's name, except as explicitly labeled identity fields in
project-admin output and in machine-readable (JSON) output.

Lookups are memory-only: render paths never stat, glob, or read project records.
Long-lived processes call :func:`refresh_project_display_snapshot` at their worker or
tick boundaries to pick up projects created or renamed by other processes. A process
that opts in through :func:`set_project_alias_map_tick_managed` (the TUI) also gets a
memory-only project alias map revalidated by that same refresh.

Thin facade over the split ``_project_display_*`` modules. Public names keep
their original ``sase.project_display_names`` import path; private
(``_``-prefixed) names live in the split modules and must be imported there.
"""

from __future__ import annotations

from sase._project_display_cache import (
    cached_project_display_snapshot,
    invalidate_project_alias_maps,
    invalidate_project_display_snapshot,
    load_project_display_snapshot,
    load_project_ref_display_snapshot,
    project_alias_maps_memoized,
    project_display_snapshot_is_warm,
    refresh_project_display_snapshot,
    set_project_alias_map_tick_managed,
    tick_managed_project_alias_map,
)
from sase._project_display_labels import (
    attach_project_display_names,
    humanize_cl_name,
    humanize_cl_names_in_text,
    humanize_safe_stem,
    humanize_vcs_refs_in_text,
    project_display_for,
    project_display_name_for,
    project_display_name_map_signature,
)
from sase._project_display_snapshot import (
    ProjectDisplayProjection,
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
    project_display_name_for_ref,
)

__all__ = [
    "ProjectDisplayProjection",
    "ProjectDisplaySnapshot",
    "ProjectRefDisplaySnapshot",
    "attach_project_display_names",
    "cached_project_display_snapshot",
    "humanize_cl_names_in_text",
    "humanize_cl_name",
    "humanize_safe_stem",
    "humanize_vcs_refs_in_text",
    "invalidate_project_alias_maps",
    "invalidate_project_display_snapshot",
    "load_project_display_snapshot",
    "load_project_ref_display_snapshot",
    "project_alias_maps_memoized",
    "project_display_for",
    "project_display_name_for_ref",
    "project_display_name_map_signature",
    "project_display_name_for",
    "project_display_snapshot_is_warm",
    "refresh_project_display_snapshot",
    "set_project_alias_map_tick_managed",
    "tick_managed_project_alias_map",
]
