"""Path-derived project-label audit and reviewed identity exemptions."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from _project_display_presentation_audit_helpers import (
    enclosing_function,
    parent_map,
    parse_source,
)

pytestmark = pytest.mark.contract
_ROOT = Path(__file__).resolve().parents[1]


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
        "src/sase/ace/tui/actions/hints/_view_target_repair.py",
        "repair_archived_prompt_path",
        "Path(project_file).parent.name",
        "Storage key passed to hidden_sidecar_clone_dir to find the agents sidecar.",
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
        "src/sase/ace/tui/models/agent_stranded.py",
        "_stranded_project_key_for_project_file",
        "Path(project_file).parent.name",
        "Stranded report cache uses the canonical project identity as an internal key.",
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
    tree = parse_source(path)
    parents = parent_map(tree)
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
                sites.add((path, enclosing_function(node, parents), ast.unparse(node)))
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
        sites.add((path, enclosing_function(candidate, parents), expression))
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
