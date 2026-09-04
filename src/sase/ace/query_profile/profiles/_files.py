"""The flat Files dialect. No sigils or macros."""

from __future__ import annotations

from sase.core.artifact_file_types import ARTIFACT_FILE_KINDS

from ..registry import HOST_PREDICATES
from ..types import ArtifactQuerySchema, QueryFieldSpec

#: Mirrors ``sase.ace.tui.widgets.artifacts.files_filtering.FILE_ORIGIN_VALUES``.
_FILE_ORIGIN_VALUES: tuple[str, ...] = ("ref", "created", "capture")


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
            searchable=key == "id",
            hint=hint,
        )
        for key, hint in (
            ("id", "logical file id"),
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
        identity_field="id",
    )


__all__ = ["files_query_schema"]
