"""Syntax-aware guards for audited project-display presentation boundaries."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

_ROOT = Path(__file__).resolve().parents[1]


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


def _parse(path: str) -> ast.Module:
    source_path = _ROOT / path
    return ast.parse(source_path.read_text(encoding="utf-8"), filename=path)


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def _root_name(node: ast.AST) -> str:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def _is_identity_attribute(node: ast.Attribute) -> bool:
    if node.attr in _IDENTITY_ATTRIBUTES:
        return True
    return node.attr == "name" and _root_name(node) in _NAME_IDENTITY_BASES


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def _enclosing_function(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
) -> str:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        current = parents.get(current)
    return "<module>"


def _is_projected_before_sink(
    node: ast.AST,
    sink: ast.Call,
    parents: dict[ast.AST, ast.AST],
) -> bool:
    current = parents.get(node)
    while current is not None and current is not sink:
        if isinstance(current, ast.Call) and _call_name(current) in _PROJECTORS:
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
        tree = _parse(path)
        parents = _parent_map(tree)
        for sink in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if _call_name(sink) not in _SINK_CALLS:
                continue
            function = _enclosing_function(sink, parents)
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
        tree = _parse(exemption.path)
        parents = _parent_map(tree)
        matching = [
            node
            for node in ast.walk(tree)
            if ast.unparse(node) == exemption.expression
            and _enclosing_function(node, parents) == exemption.function
        ]
        assert matching, (
            f"stale project-display exemption: {exemption.path} "
            f"{exemption.function} {exemption.expression}"
        )


def test_patch_completion_catalog_projects_display_fields() -> None:
    """Completion name/tag fields cannot directly consume Patch identity."""
    path = "src/sase/xprompt/vcs_project_completion.py"
    tree = _parse(path)
    parents = _parent_map(tree)
    violations: list[str] = []
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        if _call_name(call) != "VcsProjectEntry":
            continue
        if _enclosing_function(call, parents) != "_build_entries":
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


_PROJECT_METADATA_FLOW_FILES = (
    "src/sase/ace/tui/actions/_state_init_late.py",
    "src/sase/ace/tui/modals/statistics_pane_data.py",
    "src/sase/ace/tui/modals/statistics_pane_rendering.py",
    "src/sase/ace/tui/modals/statistics_pane_projects.py",
    "src/sase/ace/tui/modals/statistics_pane_views.py",
    "src/sase/ace/tui/modals/project_discovery.py",
    "src/sase/ace/tui/modals/project_select_modal.py",
    "src/sase/ace/tui/modals/prompt_stash_row.py",
    "src/sase/ace/tui/modals/_prompt_stash_preview.py",
    "src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash_store.py",
    "src/sase/ace/tui/actions/agents/_notification_launch_approval.py",
)
_ALLOWED_METADATA_LOADERS = {
    (
        "src/sase/ace/tui/actions/_state_init_late.py",
        "_project_commits_startup_display_name",
        "load_project_ref_display_snapshot",
    ): "Commits projects one merged scope before mount so first paint and collection agree.",
    (
        "src/sase/ace/tui/modals/statistics_pane_data.py",
        "load_statistics_view",
        "load_project_display_snapshot",
    ): "Statistics loads its display snapshot in the threaded view loader.",
    (
        "src/sase/ace/tui/modals/project_discovery.py",
        "load_launchable_project_snapshot",
        "list_project_records",
    ): "Project picker discovery runs inside its off-thread loader.",
    (
        "src/sase/ace/tui/modals/project_discovery.py",
        "is_launchable_project",
        "list_project_records",
    ): "Explicit launch-target validation is a resolution boundary, not rendering.",
    (
        "src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash_store.py",
        "_read_prompt_stash_presentation_snapshot",
        "load_project_display_snapshot",
    ): "Prompt-stash entries and labels are batch-loaded together on a worker.",
    (
        "src/sase/ace/tui/actions/agents/_notification_launch_approval.py",
        "_read_launch_approval_task_metadata",
        "load_project_display_snapshot",
    ): "Launch approval resolves its task label inside the tracked task worker.",
}


def test_project_metadata_loaders_stay_at_reviewed_tui_worker_boundaries() -> None:
    """Audited render/navigation flows cannot grow lifecycle metadata I/O."""
    actual: set[tuple[str, str, str]] = set()
    for path in _PROJECT_METADATA_FLOW_FILES:
        tree = _parse(path)
        parents = _parent_map(tree)
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            name = _call_name(call)
            if name not in {
                "list_project_records",
                "load_project_display_snapshot",
                "load_project_ref_display_snapshot",
            }:
                continue
            actual.add((path, _enclosing_function(call, parents), name))

    assert actual == set(_ALLOWED_METADATA_LOADERS), (
        "project metadata loader sites changed:\n"
        f"unexpected={sorted(actual - set(_ALLOWED_METADATA_LOADERS))}\n"
        f"missing={sorted(set(_ALLOWED_METADATA_LOADERS) - actual)}"
    )
    assert all(reason.strip() for reason in _ALLOWED_METADATA_LOADERS.values())


_PURE_TUI_RENDER_FILES = (
    "src/sase/ace/tui/modals/statistics_pane_rendering.py",
    "src/sase/ace/tui/modals/statistics_pane_projects.py",
    "src/sase/ace/tui/modals/statistics_pane_views.py",
    "src/sase/ace/tui/modals/prompt_stash_row.py",
    "src/sase/ace/tui/modals/_prompt_stash_preview.py",
)
_FORBIDDEN_RENDER_CALLS = {
    "Popen",
    "exists",
    "glob",
    "is_dir",
    "is_file",
    "list_project_records",
    "load_project_display_snapshot",
    "lstat",
    "open",
    "read_bytes",
    "read_text",
    "rglob",
    "run",
    "stat",
    "system",
}


def test_audited_tui_render_helpers_are_free_of_io_and_subprocess_calls() -> None:
    violations: list[str] = []
    for path in _PURE_TUI_RENDER_FILES:
        tree = _parse(path)
        parents = _parent_map(tree)
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            name = _call_name(call)
            if name in _FORBIDDEN_RENDER_CALLS:
                violations.append(
                    f"{path}:{call.lineno} {_enclosing_function(call, parents)} calls {name}"
                )
    assert not violations, "\n".join(violations)
