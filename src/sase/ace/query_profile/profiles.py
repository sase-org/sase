"""Concrete :class:`ArtifactQuerySchema` definitions for every Artifacts pane.

Each built-in constructor below is a Python-authored description of a
dialect that already exists in the codebase, hand-checked against its real
source of truth (the Patch tokenizer's property/shorthand tables for
Patches, and each flat pane's ``filter_query`` module for Stitches, Beads,
Plans, and Files) so the compiled profile preserves that dialect's current
canonical behavior byte-for-byte. :func:`provider_query_schema` instead
*derives* a schema generically from a document provider's declared
``ref.properties``, proving the profile shape needs no per-provider Python.

This module intentionally imports only pure domain/backend constants (never
Textual widgets) to stay usable from non-TUI consumers such as the Rust
binding and CLI explainability surfaces.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, get_args

from sase.ace.query.tokenizer import STATUS_SHORTHANDS
from sase.ace.query.tokenizer import VALID_PROPERTY_KEYS as _PATCH_PROPERTY_KEYS
from sase.bead.filter_query import BEAD_HAS_VALUES, DERIVED_BEAD_STATUS_VALUES
from sase.bead.model import BeadTier
from sase.bead_status_presentation import bead_status_display_order
from sase.bead_type_presentation import BEAD_TYPE_VALUES
from sase.core.artifact_file_types import ARTIFACT_FILE_KINDS
from sase.core.vcs_log_wire import CommitOrigin
from sase.phase_size_presentation import PHASE_SIZE_VALUES
from sase.vcs_provider._types import MergeVisibility

from .registry import HOST_PREDICATES
from .types import (
    ArtifactQuerySchema,
    FieldValueKind,
    QueryFieldSpec,
    QueryMacroSpec,
    QuerySigilSpec,
)

#: Mirrors ``sase.ace.tui.widgets.artifacts.files_filtering.FILE_ORIGIN_VALUES``.
_FILE_ORIGIN_VALUES: tuple[str, ...] = ("ref", "created", "capture")
_COMMIT_ORIGIN_VALUES: tuple[str, ...] = get_args(CommitOrigin)
_MERGE_VISIBILITY_VALUES: tuple[str, ...] = get_args(MergeVisibility)

_PATCH_SEARCHABLE_PROPERTY_KEYS = frozenset({"status", "project", "name", "origin"})
_PATCH_PROPERTY_HINTS: dict[str, str] = {
    "status": "patch status",
    "project": "project key or display name",
    "ancestor": "patch or ancestor name",
    "name": "exact patch name",
    "sibling": "shares the same __N revert family",
    "origin": "sase, external, or unknown",
}


def patches_query_schema() -> ArtifactQuerySchema:
    """The boolean Patch dialect: sigils, macros, and predicates included."""

    property_fields = tuple(
        QueryFieldSpec(
            key=key,
            value_kind="string",
            searchable=key in _PATCH_SEARCHABLE_PROPERTY_KEYS,
            exact_match=True,
            hint=_PATCH_PROPERTY_HINTS.get(key, ""),
        )
        for key in sorted(_PATCH_PROPERTY_KEYS)
    )
    search_only_fields = tuple(
        QueryFieldSpec(key=key, filterable=False, searchable=True, hint=hint)
        for key, hint in (
            ("description", "patch description"),
            ("refs", "referenced artifact/task ids"),
            ("parent", "immediate parent patch name"),
            ("pr_url", "PR/CL url (alias cl)"),
            ("notes", "stitch, hook, comment, and mentor notes and status suffixes"),
        )
    )
    sigils = (
        QuerySigilSpec("+", "project"),
        QuerySigilSpec("^", "ancestor"),
        QuerySigilSpec("~", "sibling"),
        QuerySigilSpec("&", "name"),
    )
    macros = tuple(
        QueryMacroSpec("%", letter, "status", value)
        for letter, value in sorted(STATUS_SHORTHANDS.items())
    )
    return ArtifactQuerySchema(
        pane_id="patches",
        boolean=True,
        fields=property_fields + search_only_fields,
        sigils=sigils,
        predicates=tuple(sorted(HOST_PREDICATES)),
        any_special=True,
        macros=macros,
        free_text_hint=(
            "name, description, status, origin, project, refs, parent, "
            "pr_url, notes (implicit AND)"
        ),
    )


def stitches_query_schema() -> ArtifactQuerySchema:
    """The flat Stitches (commits) dialect. No sigils or macros."""

    fields = (
        QueryFieldSpec(
            key="project",
            exact_match=True,
            hint="single project name; omitted means all projects",
        ),
        QueryFieldSpec(
            key="repo",
            repeatable=True,
            negatable=True,
            exact_match=True,
            hint="repository name or alias",
        ),
        QueryFieldSpec(
            key="author",
            repeatable=True,
            negatable=True,
            hint="name or email substring",
        ),
        QueryFieldSpec(
            key="origin",
            value_kind="enum",
            static_values=_COMMIT_ORIGIN_VALUES,
            repeatable=True,
            negatable=True,
            hint="commit origin: stitch, auto, manual",
        ),
        QueryFieldSpec(
            key="since",
            value_kind="date",
            hint="from an instant or the start of a named day",
        ),
        QueryFieldSpec(
            key="until",
            value_kind="date",
            hint="through an instant or the full named day",
        ),
        QueryFieldSpec(
            key="sidecar",
            value_kind="bool",
            static_values=("true", "false"),
            hint="include sidecar repositories",
        ),
        QueryFieldSpec(
            key="merges",
            value_kind="enum",
            static_values=_MERGE_VISIBILITY_VALUES,
            hint="merge-commit visibility: hide, show, or only",
        ),
        QueryFieldSpec(key="limit", hint="row cap or all"),
        QueryFieldSpec(
            key="subject",
            filterable=False,
            searchable=True,
            hint="commit subject line",
        ),
    )
    return ArtifactQuerySchema(
        pane_id="stitches",
        boolean=False,
        fields=fields,
        predicates=tuple(sorted(HOST_PREDICATES)),
        any_special=True,
        free_text_hint="subject terms (AND)",
    )


def beads_query_schema() -> ArtifactQuerySchema:
    """The flat Beads dialect. No sigils or macros."""

    enum_fields = (
        QueryFieldSpec(
            key="type",
            value_kind="enum",
            static_values=BEAD_TYPE_VALUES,
            repeatable=True,
            negatable=True,
            hint=", ".join(BEAD_TYPE_VALUES),
        ),
        QueryFieldSpec(
            key="tier",
            value_kind="enum",
            static_values=tuple(value.value for value in BeadTier),
            repeatable=True,
            negatable=True,
            hint="plan or epic",
        ),
        QueryFieldSpec(
            key="status",
            value_kind="enum",
            static_values=(*bead_status_display_order(), *DERIVED_BEAD_STATUS_VALUES),
            repeatable=True,
            negatable=True,
            hint="open, closed, blocked, triage",
        ),
        QueryFieldSpec(
            key="size",
            value_kind="enum",
            static_values=PHASE_SIZE_VALUES,
            repeatable=True,
            negatable=True,
            hint="xsmall through xlarge",
        ),
        QueryFieldSpec(
            key="has",
            value_kind="enum",
            static_values=BEAD_HAS_VALUES,
            repeatable=True,
            negatable=True,
            hint="+1, plan, bug, deps, notes, triage",
        ),
    )
    _exact_string_fields = frozenset({"project", "bug", "label"})
    string_fields = tuple(
        QueryFieldSpec(
            key=key,
            repeatable=True,
            negatable=True,
            exact_match=key in _exact_string_fields,
            hint=hint,
        )
        for key, hint in (
            ("project", "project key or display name"),
            ("assignee", "assigned person or agent"),
            ("owner", "owner email or name"),
            ("model", "work model"),
            ("bug", "none, open, #42"),
            ("label", "provider issue label"),
        )
    )
    date_fields = tuple(
        QueryFieldSpec(
            key=key,
            value_kind="date",
            repeatable=True,
            negatable=True,
            hint="Nh/Nd/Nw, today, YYYY-MM-DD",
        )
        for key in ("since", "until")
    )
    search_only_fields = tuple(
        QueryFieldSpec(key=key, filterable=False, searchable=True, hint="free text")
        for key in ("id", "title", "body", "refs")
    )
    return ArtifactQuerySchema(
        pane_id="beads",
        boolean=False,
        fields=enum_fields + string_fields + date_fields + search_only_fields,
        predicates=tuple(sorted(HOST_PREDICATES)),
        any_special=True,
        free_text_hint="id, title, body, refs (AND)",
    )


def plans_query_schema() -> ArtifactQuerySchema:
    """The flat Plans dialect. No sigils or macros.

    None of ``kind``/``status``/``tier`` are enum-validated today (unlike
    the equivalent Beads keys), so they compile as plain strings even though
    the filter bar offers static completion hints for them.
    """

    string_fields = tuple(
        QueryFieldSpec(
            key=key, repeatable=True, negatable=True, exact_match=True, hint=hint
        )
        for key, hint in (
            ("kind", "proposal, active, archive, plans, research"),
            ("status", "proposed or plan frontmatter status"),
            ("tier", "tale, epic, plan"),
            ("project", "project key or display name"),
        )
    )
    date_fields = tuple(
        QueryFieldSpec(key=key, value_kind="date", hint="Nh/Nd/Nw, today, YYYY-MM-DD")
        for key in ("since", "until")
    )
    search_only_fields = tuple(
        QueryFieldSpec(key=key, filterable=False, searchable=True, hint="free text")
        for key in ("title", "body", "path")
    )
    return ArtifactQuerySchema(
        pane_id="ref:plan",
        boolean=False,
        fields=string_fields + date_fields + search_only_fields,
        predicates=tuple(sorted(HOST_PREDICATES)),
        any_special=True,
        free_text_hint="title, body, path (AND)",
    )


def files_query_schema() -> ArtifactQuerySchema:
    """The flat Files dialect. No sigils or macros."""

    enum_fields = (
        QueryFieldSpec(
            key="kind",
            value_kind="enum",
            static_values=ARTIFACT_FILE_KINDS,
            repeatable=True,
            negatable=True,
            hint="stored artifact kind",
        ),
        QueryFieldSpec(
            key="origin",
            value_kind="enum",
            static_values=_FILE_ORIGIN_VALUES,
            repeatable=True,
            negatable=True,
            hint="explicit or default",
        ),
    )
    string_fields = tuple(
        QueryFieldSpec(
            key=key,
            repeatable=True,
            negatable=True,
            exact_match=True,
            hint=hint,
        )
        for key, hint in (
            ("project", "project key"),
            ("agent", "agent name"),
            ("workflow", "workflow name"),
        )
    )
    date_fields = tuple(
        QueryFieldSpec(
            key=key,
            value_kind="date",
            negatable=True,
            hint="YYYY-MM-DD, YYYY-MM, Nd/Nw/Nm",
        )
        for key in ("since", "until")
    )
    search_only_fields = tuple(
        QueryFieldSpec(key=key, filterable=False, searchable=True, hint="free text")
        for key in ("label", "stored_path", "source_path")
    )
    return ArtifactQuerySchema(
        pane_id="files",
        boolean=False,
        fields=enum_fields + string_fields + date_fields + search_only_fields,
        predicates=tuple(sorted(HOST_PREDICATES)),
        any_special=True,
        free_text_hint="label, stored path, source path (AND)",
    )


_PROVIDER_TYPE_KINDS: dict[str, FieldValueKind] = {
    "string": "string",
    "text": "string",
    "datetime": "date",
    "date": "date",
    "bool": "bool",
    "boolean": "bool",
    "int": "int",
    "integer": "int",
    "enum": "enum",
}


def provider_query_schema(
    kind: str, spec: Mapping[str, Any] | None
) -> ArtifactQuerySchema:
    """Derive a flat-mode schema from a document provider's ``ref.properties``.

    Providers declare fields and facts only: the profile compiler never
    grants a provider sigils or macros. Host predicates are shared with the
    fixed panes. An unrecognized declared ``type`` degrades to ``"string"``
    rather than raising, matching the epic's "malformed values degrade per
    entry" policy for provider input.
    """

    ref = spec.get("ref") if isinstance(spec, Mapping) else None
    properties = ref.get("properties") if isinstance(ref, Mapping) else None
    fields: list[QueryFieldSpec] = []
    if isinstance(properties, Mapping):
        for name in sorted(str(key) for key in properties if str(key)):
            declared = properties[name]
            value_kind, repeatable, static_values = _provider_value_kind(declared)
            fields.append(
                QueryFieldSpec(
                    key=name,
                    value_kind=value_kind,
                    static_values=static_values,
                    searchable=_provider_searchable(declared, value_kind),
                    repeatable=repeatable,
                    negatable=True,
                    hint=f"declared {kind} property",
                )
            )
    searchable_keys = tuple(item.key for item in fields if item.searchable)
    free_text_hint = f"{', '.join(searchable_keys)} (AND)" if searchable_keys else ""
    return ArtifactQuerySchema(
        pane_id=f"ref:{kind}",
        boolean=False,
        fields=tuple(fields),
        predicates=tuple(sorted(HOST_PREDICATES)),
        any_special=True,
        free_text_hint=free_text_hint,
    )


def _provider_value_kind(
    declared: object,
) -> tuple[FieldValueKind, bool, tuple[str, ...]]:
    if not isinstance(declared, Mapping):
        return "string", False, ()
    raw_type = declared.get("type")
    if raw_type == "string_list":
        return "string", True, ()
    if isinstance(raw_type, str):
        value_kind = _PROVIDER_TYPE_KINDS.get(raw_type, "string")
        return value_kind, False, _enum_values(declared) if value_kind == "enum" else ()
    return "string", False, ()


def _enum_values(declared: Mapping[str, Any]) -> tuple[str, ...]:
    values = declared.get("values")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return ()
    return tuple(
        dict.fromkeys(item.strip() for item in values if isinstance(item, str) and item)
    )


def _provider_searchable(declared: object, value_kind: FieldValueKind) -> bool:
    if isinstance(declared, Mapping) and "searchable" in declared:
        return bool(declared["searchable"])
    return value_kind == "string"


__all__ = [
    "beads_query_schema",
    "files_query_schema",
    "patches_query_schema",
    "plans_query_schema",
    "provider_query_schema",
    "stitches_query_schema",
]
