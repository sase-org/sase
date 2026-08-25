"""The flat Procs dialect. No sigils, macros, or host predicates."""

from __future__ import annotations

from sase.ace.query.limit_token import HOST_LIMIT_HINT
from sase.main.parser_proc import PROC_KIND_CHOICES, PROC_STATUS_CHOICES

from ..types import ArtifactQuerySchema, QueryFieldSpec


def procs_query_schema() -> ArtifactQuerySchema:
    """The flat Procs dialect. No sigils, macros, or host predicates.

    Free text (and its explicit ``text:`` spelling) searches the command
    string, row label, and retained output. Every field is negatable, and
    the boolean fields take the bare shorthand (a bare ``monitor`` means
    ``monitor:true``).
    """

    string_fields = (
        QueryFieldSpec(
            key="text",
            negatable=True,
            hint="command, label, output -- same corpus as bare free text",
        ),
        QueryFieldSpec(
            key="cmd",
            searchable=True,
            negatable=True,
            hint="command string only",
        ),
        QueryFieldSpec(
            key="out",
            searchable=True,
            negatable=True,
            hint="retained output only (last 32 KB)",
        ),
        QueryFieldSpec(
            key="name",
            searchable=True,
            negatable=True,
            hint="row label / display name",
        ),
        QueryFieldSpec(
            key="agent",
            negatable=True,
            hint="monitor row's member agent name",
        ),
        QueryFieldSpec(
            key="project",
            exact_match=True,
            negatable=True,
            hint="project key or display name",
        ),
    )
    enum_fields = (
        QueryFieldSpec(
            key="status",
            value_kind="enum",
            static_values=PROC_STATUS_CHOICES,
            negatable=True,
            hint=", ".join(PROC_STATUS_CHOICES),
        ),
        QueryFieldSpec(
            key="kind",
            value_kind="enum",
            static_values=PROC_KIND_CHOICES,
            negatable=True,
            hint=", ".join(PROC_KIND_CHOICES),
        ),
    )
    bool_fields = (
        QueryFieldSpec(
            key="monitor",
            value_kind="bool",
            negatable=True,
            hint="a sase monitor start proc shell",
        ),
        QueryFieldSpec(
            key="running",
            value_kind="bool",
            negatable=True,
            hint="active and owned by a live session",
        ),
        QueryFieldSpec(
            key="failed",
            value_kind="bool",
            negatable=True,
            hint="terminal status is error or killed",
        ),
    )
    int_fields = (
        QueryFieldSpec(key="exit", value_kind="int", negatable=True, hint="exit code"),
        QueryFieldSpec(
            key="min",
            value_kind="int",
            negatable=True,
            hint="runtime at least N seconds (or 5m, 2h, 1d)",
        ),
        QueryFieldSpec(
            key="max",
            value_kind="int",
            negatable=True,
            hint="runtime at most N seconds (or 5m, 2h, 1d)",
        ),
    )
    date_fields = (
        QueryFieldSpec(
            key="after",
            value_kind="date",
            negatable=True,
            hint="completed at or after (Nh/Nd/Nw, today, YYYY-MM-DD)",
        ),
        QueryFieldSpec(
            key="before",
            value_kind="date",
            negatable=True,
            hint="completed at or before (Nh/Nd/Nw, today, YYYY-MM-DD)",
        ),
        QueryFieldSpec(
            key="since",
            value_kind="date",
            negatable=True,
            hint="started at or after (Nh/Nd/Nw, today, YYYY-MM-DD)",
        ),
        QueryFieldSpec(
            key="until",
            value_kind="date",
            negatable=True,
            hint="started at or before (Nh/Nd/Nw, today, YYYY-MM-DD)",
        ),
    )
    limit_field = (QueryFieldSpec(key="limit", hint=HOST_LIMIT_HINT),)
    return ArtifactQuerySchema(
        pane_id="procs",
        boolean=False,
        fields=(
            string_fields
            + enum_fields
            + bool_fields
            + int_fields
            + date_fields
            + limit_field
        ),
        free_text_hint="command, label, output (implicit AND)",
    )


__all__ = ["procs_query_schema"]
