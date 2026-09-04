"""The flat Stitches (commits) dialect. No sigils or macros."""

from __future__ import annotations

from typing import get_args

from sase.core.vcs_log_wire import CommitOrigin
from sase.vcs_provider._types import MergeVisibility

from ..registry import HOST_PREDICATES
from ..types import ArtifactQuerySchema, QueryFieldSpec

_COMMIT_ORIGIN_VALUES: tuple[str, ...] = get_args(CommitOrigin)
_MERGE_VISIBILITY_VALUES: tuple[str, ...] = get_args(MergeVisibility)


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
            key="type",
            repeatable=True,
            negatable=True,
            exact_match=True,
            static_values=("manual", "automatic", "stitch", "merge", "patch"),
            hint="commit labels or observed SASE_TYPE value",
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
            key="sha",
            repeatable=True,
            negatable=True,
            hint="commit SHA prefix",
        ),
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
        identity_field="sha",
    )


__all__ = ["stitches_query_schema"]
