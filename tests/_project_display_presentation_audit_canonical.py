"""Canonical identity sink and completion-catalog audits."""

from __future__ import annotations

import ast
from dataclasses import dataclass

import pytest

from _project_display_presentation_audit_helpers import (
    call_name,
    enclosing_function,
    parent_map,
    parse_source,
)

pytestmark = pytest.mark.contract


@dataclass(frozen=True, slots=True)
class _CanonicalExemption:
    path: str
    function: str
    expression: str
    rationale: str
    sink_context: str = ""


# These sites intentionally retain canonical identity. Keeping the site and
# rationale together makes any expansion of the exemption set an explicit
# presentation-boundary review decision.
_CANONICAL_EXEMPTIONS = (
    _CanonicalExemption(
        "src/sase/main/patch_current.py",
        "_patch_payload",
        "cs.name",
        "Stable JSON output must retain the exact Patch identity.",
    ),
    _CanonicalExemption(
        "src/sase/main/patch_current.py",
        "_patch_payload",
        "cs.project_basename",
        "Stable JSON output must retain the canonical project key.",
    ),
    _CanonicalExemption(
        "src/sase/main/patch_current.py",
        "_patch_payload",
        "cs.parent",
        "Stable JSON output must retain the exact parent identity.",
    ),
    _CanonicalExemption(
        "src/sase/main/workspace_handler_list.py",
        "handle_list",
        "ctx.project_name",
        "Project resolution and JSON output use the canonical project key.",
    ),
    _CanonicalExemption(
        "src/sase/main/workspace_handler_list.py",
        "_print_all_projects_human",
        "row.project",
        "WorkspaceInventoryRecord.project is an already-projected label; project_key owns identity.",
        "formatted",
    ),
    _CanonicalExemption(
        "src/sase/main/workspace_handler_list.py",
        "_print_inventory_issues",
        "issue.project",
        "Workspace inventory issues already carry the projected project label.",
        "formatted",
    ),
    _CanonicalExemption(
        "src/sase/ace/tui/modals/project_select_modal.py",
        "_load_items",
        "project.project_key",
        "Interactive project options retain a canonical selection identity beside their label.",
        "keyword:project_name",
    ),
    _CanonicalExemption(
        "src/sase/ace/tui/modals/project_select_modal.py",
        "_load_items",
        "cs.project_basename",
        "Patch options retain the canonical owning project for replay and lookup.",
        "keyword:project_name",
    ),
    _CanonicalExemption(
        "src/sase/ace/tui/modals/project_select_modal.py",
        "_load_items",
        "cs.name",
        "Patch options retain the exact Patch identity beside selection_label.",
        "keyword:cl_name",
    ),
    _CanonicalExemption(
        "src/sase/ace/tui/modals/prompt_stash_row.py",
        "stash_row_label",
        "entry.project",
        "Prompt-stash storage remains canonical and is projected before the row is painted.",
    ),
    _CanonicalExemption(
        "src/sase/ace/tui/modals/_prompt_stash_preview.py",
        "_build_prompt_stash_metadata",
        "entry.project",
        "Prompt-stash storage remains canonical and is projected before metadata is painted.",
    ),
    _CanonicalExemption(
        "src/sase/ace/tui/actions/agents/_notification_launch_approval.py",
        "_read_launch_approval_task_metadata",
        "workspace.get('project_name')",
        "Launch-request metadata remains canonical while the worker derives a display-only task label.",
    ),
    _CanonicalExemption(
        "src/sase/ace/tui/actions/agents/_notification_launch_approval.py",
        "_read_launch_approval_task_metadata",
        "workspace.get('cl_name')",
        "The task retains exact Patch metadata while only display_name is projected.",
    ),
    _CanonicalExemption(
        "src/sase/ace/tui/actions/agents/_notification_launch_approval.py",
        "_read_launch_approval_task_metadata",
        "workspace.get('project_file')",
        "Project paths are exact storage identities and must never be humanized.",
    ),
)

_AUDITED_RENDERERS = (
    "src/sase/ace/display.py",
    "src/sase/ace/tui/modals/statistics_pane_rendering.py",
    "src/sase/ace/tui/modals/statistics_pane_projects.py",
    "src/sase/ace/tui/modals/statistics_pane_views.py",
    "src/sase/ace/tui/modals/project_select_modal.py",
    "src/sase/ace/tui/modals/prompt_stash_row.py",
    "src/sase/ace/tui/modals/_prompt_stash_preview.py",
    "src/sase/diagnostics/render.py",
    "src/sase/main/search_handler.py",
    "src/sase/main/workspace_handler_list.py",
    "src/sase/ace/tui/widgets/_agent_list_render_agent.py",
    "src/sase/ace/tui/widgets/prompt_panel/_agent_display_clan_identity.py",
    "src/sase/ace/tui/widgets/prompt_panel/_identity_header_compact.py",
    "src/sase/ace/tui/actions/agent_workflow/_launch_submit_helpers.py",
    "src/sase/ace/tui/actions/agent_workflow/_launch_submission.py",
)

_SINK_CALLS = {
    "Label",
    "Option",
    "Static",
    "Text",
    "add_row",
    "append",
    "notify",
    "print",
    "update",
}
_PROJECTORS = {
    "_patch_cell",
    "_project_cell",
    "humanize_cl_name",
    "humanize_cl_names_in_text",
    "humanize_safe_stem",
    "humanize_vcs_refs_in_text",
    "label_for",
    "project_display_for",
    "project_display_name_for",
}
_IDENTITY_ATTRIBUTES = {
    "patch_key",
    "cl_name",
    "group_key",
    "parent",
    "project",
    "project_basename",
    "project_key",
    "project_name",
}
_NAME_IDENTITY_BASES = {"change", "patch", "claim", "cs"}


def _root_name(node: ast.AST) -> str:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def _is_identity_attribute(node: ast.Attribute) -> bool:
    if node.attr in _IDENTITY_ATTRIBUTES:
        return True
    return node.attr == "name" and _root_name(node) in _NAME_IDENTITY_BASES


def _is_projected_before_sink(
    node: ast.AST,
    sink: ast.Call,
    parents: dict[ast.AST, ast.AST],
) -> bool:
    current = parents.get(node)
    while current is not None and current is not sink:
        if isinstance(current, ast.Call) and call_name(current) in _PROJECTORS:
            return True
        current = parents.get(current)
    return False


def _sink_context(
    node: ast.AST,
    sink: ast.Call,
    parents: dict[ast.AST, ast.AST],
) -> str:
    current = parents.get(node)
    while current is not None and current is not sink:
        if isinstance(current, ast.keyword):
            return f"keyword:{current.arg}"
        if isinstance(current, ast.FormattedValue):
            return "formatted"
        current = parents.get(current)
    return "direct"


def _exemption_map() -> dict[tuple[str, str, str, str], str]:
    return {
        (item.path, item.function, item.expression, item.sink_context): item.rationale
        for item in _CANONICAL_EXEMPTIONS
        if item.sink_context
    }


def test_audited_human_sinks_do_not_render_canonical_identity_directly() -> None:
    """Direct identity fields in known human sinks require projection or review."""
    exemptions = _exemption_map()
    violations: list[str] = []
    for path in _AUDITED_RENDERERS:
        tree = parse_source(path)
        parents = parent_map(tree)
        for sink in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if call_name(sink) not in _SINK_CALLS:
                continue
            function = enclosing_function(sink, parents)
            for node in ast.walk(sink):
                if not isinstance(node, ast.Attribute) or not _is_identity_attribute(
                    node
                ):
                    continue
                if _is_projected_before_sink(node, sink, parents):
                    continue
                expression = ast.unparse(node)
                context = _sink_context(node, sink, parents)
                if (path, function, expression, context) in exemptions:
                    continue
                violations.append(
                    f"{path}:{node.lineno} {function} renders {expression} directly"
                )

    assert not violations, "\n".join(violations)


def test_canonical_exemptions_name_existing_sites_and_rationales() -> None:
    """Exemptions are deliberate, documented, and cannot silently go stale."""
    assert len(_exemption_map()) == sum(
        bool(item.sink_context) for item in _CANONICAL_EXEMPTIONS
    )
    for exemption in _CANONICAL_EXEMPTIONS:
        assert exemption.rationale.strip()
        tree = parse_source(exemption.path)
        parents = parent_map(tree)
        matching = [
            node
            for node in ast.walk(tree)
            if ast.unparse(node) == exemption.expression
            and enclosing_function(node, parents) == exemption.function
        ]
        assert matching, (
            f"stale project-display exemption: {exemption.path} "
            f"{exemption.function} {exemption.expression}"
        )


def test_patch_completion_catalog_projects_display_fields() -> None:
    """Completion name/tag fields cannot directly consume Patch identity."""
    path = "src/sase/macro/vcs_project_completion.py"
    tree = parse_source(path)
    parents = parent_map(tree)
    violations: list[str] = []
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        if call_name(call) != "VcsProjectEntry":
            continue
        if enclosing_function(call, parents) != "_build_entries":
            continue
        for keyword in call.keywords:
            if keyword.arg not in {"display_tag", "name"}:
                continue
            for node in ast.walk(keyword.value):
                if (
                    isinstance(node, ast.Attribute)
                    and _is_identity_attribute(node)
                    and not _is_projected_before_sink(node, call, parents)
                ):
                    violations.append(
                        f"{path}:{node.lineno} {keyword.arg} consumes {ast.unparse(node)}"
                    )
    assert not violations, "\n".join(violations)
