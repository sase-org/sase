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
    path = "src/sase/macro/vcs_project_completion.py"
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
    "src/sase/ace/tui/actions/agents/_loading_compute.py",
    "src/sase/ace/tui/models/agent_loader.py",
    "src/sase/ace/dismissed_agents_bundles.py",
    "src/sase/ace/tui/actions/event_refresh/_auto_refresh_surfaces.py",
    "src/sase/agents/_wait_live_rows.py",
    "src/sase/axe/lumberjack.py",
)
_PROJECT_METADATA_LOADER_NAMES = {
    "list_project_records",
    "load_project_display_snapshot",
    "load_project_ref_display_snapshot",
    "refresh_project_display_snapshot",
}
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
    (
        "src/sase/ace/tui/actions/agents/_loading_compute.py",
        "compute_apply_loaded_agents",
        "refresh_project_display_snapshot",
    ): "Agent-load worker revalidates cross-process labels before attaching names.",
    (
        "src/sase/ace/tui/models/agent_loader.py",
        "_filter_and_cap_windowed_agents_live",
        "refresh_project_display_snapshot",
    ): "Windowed live-query path revalidates before attaching names.",
    (
        "src/sase/ace/dismissed_agents_bundles.py",
        "_load_bundle_paths",
        "refresh_project_display_snapshot",
    ): "Dismissed-bundle loads revalidate before attaching names.",
    (
        "src/sase/ace/tui/actions/event_refresh/_auto_refresh_surfaces.py",
        "_run_auto_refresh_surfaces",
        "refresh_project_display_snapshot",
    ): "Auto-refresh tick revalidates off-thread and dirties label surfaces.",
    (
        "src/sase/agents/_wait_live_rows.py",
        "build_wait_live_rows",
        "refresh_project_display_snapshot",
    ): "Wait live rows revalidate once per poll iteration.",
    (
        "src/sase/axe/lumberjack.py",
        "_run_tick",
        "refresh_project_display_snapshot",
    ): "Lumberjack revalidates once per cycle, not per log line.",
}


def _metadata_loader_call_name(call: ast.Call) -> str | None:
    """Return the tracked loader a call invokes, including via ``to_thread``."""
    name = _call_name(call)
    if name in _PROJECT_METADATA_LOADER_NAMES:
        return name
    if name == "to_thread" and call.args:
        target = call.args[0]
        if isinstance(target, ast.Name) and target.id in _PROJECT_METADATA_LOADER_NAMES:
            return target.id
        if (
            isinstance(target, ast.Attribute)
            and target.attr in _PROJECT_METADATA_LOADER_NAMES
        ):
            return target.attr
    return None


def test_project_metadata_loaders_stay_at_reviewed_tui_worker_boundaries() -> None:
    """Audited render/navigation flows cannot grow lifecycle metadata I/O."""
    actual: set[tuple[str, str, str]] = set()
    for path in _PROJECT_METADATA_FLOW_FILES:
        tree = _parse(path)
        parents = _parent_map(tree)
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            name = _metadata_loader_call_name(call)
            if name is None:
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
    "src/sase/ace/tui/widgets/_agent_list_render_agent.py",
    "src/sase/ace/tui/widgets/prompt_panel/_agent_display_clan_identity.py",
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
    "refresh_project_display_snapshot",
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


@dataclass(frozen=True, slots=True)
class _PathLabelExemption:
    path: str
    function: str
    expression: str
    rationale: str


# Identity-only derivations of the directory key. Each site feeds grouping keys,
# navigation targets, workspace resolution, query matching, storage handles, or
# the display-map lookup itself — never a human-facing project name.
_PATH_LABEL_EXEMPTIONS = (
    _PathLabelExemption(
        "src/sase/ace/tui/models/agent.py",
        "project_file_parent_name",
        "Path(str(project_file)).parent.name",
        "The canonical identity helper every other site funnels through.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/models/agent.py",
        "is_project_agent",
        "project_file_parent_name(self.project_file)",
        "Project-agent classification compares Patch identity against the key.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/models/agent.py",
        "project_label",
        "project_file_parent_name(self.project_file)",
        "Chokepoint derives the key only to project it through the display map.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/actions/agents/_node_finder_facets.py",
        "snapshot_all_facets",
        "project_file_parent_name(agent.project_file)",
        "Node-finder facet matching joins on canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/actions/_startup_prompt_catalog_semantics.py",
        "_semantic_context_matches_selected_agent",
        "Path(project_file).parent.name",
        "Startup semantic matching compares storage identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/actions/agent_workflow/_entry_quick_launch.py",
        "_start_agent_from_agent_quick",
        "Path(agent.project_file).parent.name",
        "Launch prefix derivation; the key is projected before the toast.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/actions/agent_workflow/_entry_relaunch.py",
        "_mount_edit_relaunch_prompt_bar",
        "Path(project_file).parent.name",
        "Relaunch prompt resolves the canonical owning project.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/actions/agent_workflow/_launch_delta.py",
        "artifact_dir_from_launch_result",
        "Path(result.project_file).expanduser().parent.name",
        "Launch-result artifact directories key on storage identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/actions/agent_workflow/_launch_submit_helpers.py",
        "launch_record_context_from_prompt_context",
        "Path(ctx.project_file).expanduser().parent.name",
        "Launch records persist canonical identity, never labels.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/actions/agent_workflow/_launch_submit_helpers.py",
        "launch_record_context",
        "Path(project_file).expanduser().parent.name",
        "Launch records persist canonical identity, never labels.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/actions/agent_workflow/_launch_submit_helpers.py",
        "dispatch_payload_from_prompt_context",
        "Path(ctx.project_file).expanduser().parent.name",
        "Dispatch payloads carry canonical identity for replay and lookup.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/actions/agents/_notification_navigation.py",
        "navigate_to_patch_tab",
        "Path(project_file).parent.name",
        "Patch-tab navigation targets canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/actions/agents/_panel_tmux.py",
        "_resolve_agent_tmux_target",
        "Path(agent.project_file).parent.name",
        "Tmux window identity must stay a stable canonical key.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/actions/agents/_patch_navigation.py",
        "_read_workflow_state_cl_name",
        "Path(agent.project_file).parent.name",
        "Workflow-state Patch reads resolve the canonical project.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/actions/agents/_saved_group_records.py",
        "_agent_project_name",
        "Path(agent.project_file).parent.name",
        "Saved group records persist canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/actions/agents/_saved_group_records.py",
        "_agent_project_name",
        "Path(agent.project_file).stem",
        "Saved group records persist canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/actions/agents/_wait_helpers.py",
        "wait_bead_project_key",
        "Path(project_file).parent.name",
        "Wait-bead joins key on canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/actions/artifacts_files.py",
        "_first_file_project_agent_match",
        "Path(project_file).parent.name",
        "Artifact file matching joins on canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/command_line/sources.py",
        "_project_candidates",
        "Path(project_file).parent.name",
        "Command-line project candidates resolve storage identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/data_providers/_handles.py",
        "_handle_for_agent",
        "Path(agent.project_file).parent.name",
        "Row handles embed canonical identity for stable selection.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/modals/_runners_data.py",
        "_collect_manual_agents",
        "Path(project_file).stem",
        "Runner rows key manual agents by canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/modals/agent_workspace_tmux_modal.py",
        "build_agent_workspace_tmux_choices",
        "Path(agent.project_file).parent.name",
        "Tmux workspace choices key on stable canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/modals/revive_agent_modal.py",
        "_agent_filter_label",
        "Path(agent.project_file).parent.name",
        "Search corpus intentionally spans canonical and display spellings.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/models/_agent_associated_plan_paths.py",
        "agent_project_name",
        "Path(agent.project_file).parent.name",
        "Plan-path association joins on canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/models/_agent_runner_slot_capacity.py",
        "project_name",
        "Path(agent.project_file).parent.name",
        "Runner capacity accounting groups by canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/models/agent_bead.py",
        "_agent_project_name",
        "Path(agent.project_file).parent.name",
        "Bead association joins on canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/models/agent_epic_follow_progress.py",
        "_follow_progress_project_key",
        "Path(str(project_file)).parent.name",
        "Follow-progress joins key on canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/models/agent_live_query.py",
        "_project_basename",
        "Path(project_file).parent.name",
        "Live-query pushdown matches canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/models/agent_page_url.py",
        "resolve_agent_page_url",
        "Path(agent.project_file).parent.name",
        "Page URLs embed canonical identity for stable links.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/models/agent_wait_beads.py",
        "_wait_bead_project_key",
        "Path(project_file).parent.name",
        "Wait-bead joins key on canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/thinking/session_resolver.py",
        "_get_workspace_cwd",
        "Path(agent.project_file).parent.name",
        "Workspace resolution starts from canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/widgets/_prompt_input_bar_dispatch.py",
        "_dispatch_source_label",
        "Path(project_file).expanduser().parent.name",
        "Source key is projected through the display map before paint.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/widgets/prompt_panel/_agent_clan_aggregation.py",
        "_clan_hint_workspace_context",
        "Path(row.project_file).parent.name",
        "Workspace resolution starts from canonical identity.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/widgets/prompt_panel/_agent_commits.py",
        "_agent_plan_workspaces",
        "Path(agent.project_file).parent.name",
        "Plan workspaces carry owner identity for workspace resolution.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/widgets/prompt_panel/_agent_commits.py",
        "_primary_repo_name",
        "Path(agent.project_file).stem",
        "Stem-derived key is projected through the display map before paint.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/widgets/prompt_panel/_agent_display_header_metadata_fields.py",
        "append_agent_metadata_fields",
        "Path(agent.project_file).parent.name",
        "Macro sections receive the key for resolution beside the label.",
    ),
    _PathLabelExemption(
        "src/sase/ace/tui/widgets/prompt_panel/_agent_macro_highlighting.py",
        "_agent_project_and_workspace",
        "Path(agent.project_file).parent.name",
        "Highlight context resolves the canonical ref for workspace lookup.",
    ),
)


def _path_label_sites(
    path: str,
) -> set[tuple[str, str, str]]:
    """Return ``(path, function, expression)`` path-derived key sites in *path*."""
    tree = _parse(path)
    parents = _parent_map(tree)
    sites: set[tuple[str, str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else (func.attr if isinstance(func, ast.Attribute) else "")
            )
            if name == "project_file_parent_name":
                sites.add((path, _enclosing_function(node, parents), ast.unparse(node)))
            continue
        if not isinstance(node, ast.Attribute):
            continue
        candidate: ast.AST | None = None
        if node.attr == "name" and isinstance(node.value, ast.Attribute):
            if node.value.attr == "parent":
                candidate = node
        elif node.attr == "stem":
            candidate = node
        if candidate is None:
            continue
        expression = ast.unparse(candidate)
        if "project_file" not in expression:
            continue
        sites.add((path, _enclosing_function(candidate, parents), expression))
    return sites


def _tui_py_files() -> list[str]:
    return sorted(
        str(path.relative_to(_ROOT))
        for path in _ROOT.glob("src/sase/ace/tui/**/*.py")
        if "__pycache__" not in str(path)
    )


def test_project_labels_never_derive_from_paths() -> None:
    """No TUI label may come from a project path; identity sites are allowlisted."""
    allowed = {
        (item.path, item.function, item.expression) for item in _PATH_LABEL_EXEMPTIONS
    }
    violations: list[str] = []
    for path in _tui_py_files():
        for site in _path_label_sites(path):
            if site not in allowed:
                violations.append(f"{site[0]}:{site[1]} derives {site[2]}")
    assert not violations, "\n".join(violations)


def test_path_label_exemptions_name_existing_sites_and_rationales() -> None:
    """Path-label exemptions are deliberate, documented, and cannot go stale."""
    actual: set[tuple[str, str, str]] = set()
    for path in _tui_py_files():
        actual |= _path_label_sites(path)
    for exemption in _PATH_LABEL_EXEMPTIONS:
        assert exemption.rationale.strip()
        assert (exemption.path, exemption.function, exemption.expression) in actual, (
            f"stale path-label exemption: {exemption.path} "
            f"{exemption.function} {exemption.expression}"
        )


@dataclass(frozen=True, slots=True)
class _DisplayFallbackExemption:
    path: str
    function: str
    expression: str
    rationale: str


# Pre-existing ``project_display_name or ...`` fallbacks outside the agent-label
# chokepoint. Each owns a non-Agent display field or a query/entry identity where
# the fallback is empty or the model carries its own refresh story.
_DISPLAY_FALLBACK_EXEMPTIONS = (
    _DisplayFallbackExemption(
        "src/sase/ace/tui/bgcmd.py",
        "display_project",
        "self.project_display_name or self.project",
        "Durable oneshot rows snapshot their label at build time and refresh on rebuild.",
    ),
    _DisplayFallbackExemption(
        "src/sase/ace/patch/models/patch.py",
        "project_query_name",
        "self.project_display_name or self.project_name",
        "Exact project: query identity, not a painted label.",
    ),
    _DisplayFallbackExemption(
        "src/sase/artifact_providers/builtin_entry_patch.py",
        "resolve_patch_entry",
        "patch.project_display_name or ''",
        "Entry builder falls back to empty, never to a key.",
    ),
    _DisplayFallbackExemption(
        "src/sase/ace/tui/widgets/prompt_panel/_identity_header_compact.py",
        "_build_named_proc_compact_lines",
        "agent.project_display_name or humanize_cl_name(agent.cl_name)",
        "Named-proc rows fall back to the proc's own name, never a path or key.",
    ),
    _DisplayFallbackExemption(
        "src/sase/ace/tui/widgets/prompt_panel/_agent_display_header_metadata_identity.py",
        "append_project_fields",
        "agent.project_display_name or humanize_cl_name(agent.cl_name)",
        "Named-proc fields fall back to the proc's own name, never a path or key.",
    ),
)

# The sanctioned chokepoint: ``Agent.project_label`` plus the display-map module.
_DISPLAY_FALLBACK_CHOKPOINT = (
    "src/sase/ace/tui/models/agent.py",
    "project_label",
)
_DISPLAY_FALLBACK_CHOKPOINT_FILES = frozenset(
    {
        "src/sase/project_display_names.py",
    }
)


def _display_fallback_sites() -> dict[tuple[str, str, str], int]:
    """Map ``(path, function, or-expression)`` display fallbacks across ``src``."""
    sites: dict[tuple[str, str, str], int] = {}
    for file_path in sorted(_ROOT.glob("src/**/*.py")):
        if "__pycache__" in str(file_path):
            continue
        path = str(file_path.relative_to(_ROOT))
        tree = _parse(path)
        parents = _parent_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.Or):
                continue
            if not any(
                isinstance(value, ast.Attribute)
                and value.attr == "project_display_name"
                for value in node.values
            ):
                continue
            key = (path, _enclosing_function(node, parents), ast.unparse(node))
            sites[key] = node.lineno
    return sites


def test_project_display_name_fallback_lives_only_in_chokepoint() -> None:
    """Only Agent.project_label may fall back from project_display_name."""
    allowed = {
        (item.path, item.function, item.expression)
        for item in _DISPLAY_FALLBACK_EXEMPTIONS
    }
    violations: list[str] = []
    for (path, function, expression), lineno in _display_fallback_sites().items():
        if path in _DISPLAY_FALLBACK_CHOKPOINT_FILES:
            continue
        if (path, function) == _DISPLAY_FALLBACK_CHOKPOINT:
            continue
        if (path, function, expression) in allowed:
            continue
        violations.append(f"{path}:{lineno} {function} falls back in {expression}")
    assert not violations, "\n".join(violations)


def test_display_fallback_exemptions_name_existing_sites_and_rationales() -> None:
    """Display-fallback exemptions are deliberate, documented, and cannot go stale."""
    actual = set(_display_fallback_sites())
    assert not any(key[0] in _DISPLAY_FALLBACK_CHOKPOINT_FILES for key in actual), (
        "display-map module grew a project_display_name fallback; review it here"
    )
    for exemption in _DISPLAY_FALLBACK_EXEMPTIONS:
        assert exemption.rationale.strip()
        assert (exemption.path, exemption.function, exemption.expression) in actual, (
            f"stale display-fallback exemption: {exemption.path} "
            f"{exemption.function} {exemption.expression}"
        )
