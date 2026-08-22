"""Public bead detail API and human-readable rendering."""

from __future__ import annotations

from pathlib import Path

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.cli_detail_context import (
    artifact_reference_context,
    design_paths_are_relative,
    plan_reference_roots,
    resolve_bead_creator_url,
    resolve_bead_page_url,
)
from sase.bead.cli_detail_json import (
    issue_to_wire_dict,
    ref_to_wire_dict,
    render_issue_detail_json,
)
from sase.bead.cli_detail_render import render_issue_detail as _render_issue_detail
from sase.bead.cli_detail_resolution import (
    IssueDetail,
    IssueDetailIndex,
    IssueRef,
    resolve_issue_detail,
)
from sase.bead.cli_detail_style import DetailStyle
from sase.core.agent_identity_facade import present_agent_name


def render_issue_detail(
    detail: IssueDetail,
    *,
    relativize_design: bool,
    plan_roots: tuple[Path, ...] = (),
    reference_context: ArtifactRefContext | None = None,
    creator_url: str | None = None,
    page_url: str | None = None,
    style: DetailStyle = DetailStyle.PLAIN,
    wrap: int | None = None,
) -> str:
    """Render the established human-readable bead detail block.

    Styling is purely additive ANSI: for any *detail*, *style*, and *wrap*,
    stripping SGR escapes from the output reproduces the matching
    ``DetailStyle.PLAIN`` bytes exactly.
    """
    return _render_issue_detail(
        detail,
        relativize_design=relativize_design,
        plan_roots=plan_roots,
        reference_context=reference_context,
        creator_url=creator_url,
        page_url=page_url,
        style=style,
        wrap=wrap,
        present_creator=present_agent_name,
    )


__all__ = [
    "IssueDetail",
    "IssueDetailIndex",
    "IssueRef",
    "artifact_reference_context",
    "design_paths_are_relative",
    "issue_to_wire_dict",
    "plan_reference_roots",
    "ref_to_wire_dict",
    "render_issue_detail",
    "render_issue_detail_json",
    "resolve_bead_creator_url",
    "resolve_bead_page_url",
    "resolve_issue_detail",
]
