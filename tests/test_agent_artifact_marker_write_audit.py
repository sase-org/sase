"""Audit direct mutation sites for Tier 1-projected agent marker files."""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TRACKED_MARKER_LITERALS = (
    "agent_meta.json",
    "done.json",
    "running.json",
    "waiting.json",
    "pending_question.json",
    "workflow_state.json",
    "plan_path.json",
    "prompt_step_",
)
_MUTATION_CALL_NAMES = {
    "_write_json_file",
    "dump",
    "mkstemp",
    "remove",
    "rmtree",
    "unlink",
    "write_text",
}
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_NESTED_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_REVIEWED_MARKER_MUTATION_CONTEXTS = {
    "src/sase/ace/tui/actions/agents/_approve.py:_persist_plan_auto_approval",
    "src/sase/ace/tui/actions/agents/_killing_utils.py:delete_agent_artifacts",
    "src/sase/ace/tui/actions/agents/_notification_plan_persistence.py:"
    "persist_plan_approved",
    "src/sase/ace/tui/actions/agents/_revive_artifacts.py:_restore_agent_artifacts",
    "src/sase/ace/tui/actions/agents/_revive_artifacts.py:_restore_agent_meta",
    "src/sase/ace/tui/actions/agents/_wait_resume.py:_apply_wait",
    "src/sase/ace/tui/actions/rename.py:handle_name_result",
    "src/sase/ace/tui/models/_loaders/_running_loaders.py:load_running_home_agents",
    "src/sase/ace/tui/models/_loaders/_running_loaders.py:"
    "load_running_home_agents_from_snapshot",
    "src/sase/agent/names/_migration.py:_rewrite_artifact_json_files",
    "src/sase/agent/names/_wipe.py:_release_artifact_workspace",
    "src/sase/agent/running.py:kill_named_agent",
    "src/sase/axe/run_agent_directives.py:extract_directives_and_write_meta",
    "src/sase/axe/run_agent_exec_markers.py:clear_workflow_pdf_activity",
    "src/sase/axe/run_agent_exec_markers.py:update_workflow_pdf_status",
    "src/sase/axe/run_agent_exec_markers.py:write_done_marker_and_update_index",
    "src/sase/axe/run_agent_exec_plan_artifacts.py:write_plan_path_artifact",
    "src/sase/axe/run_agent_helpers.py:append_meta_list_field",
    "src/sase/axe/run_agent_helpers.py:create_followup_artifacts",
    "src/sase/axe/run_agent_helpers.py:handle_questions_flow",
    "src/sase/axe/run_agent_helpers.py:normalize_handoff_interruption_state",
    "src/sase/axe/run_agent_helpers.py:promote_to_workflow",
    "src/sase/axe/run_agent_helpers.py:update_meta_field",
    "src/sase/axe/run_agent_helpers.py:update_meta_suffix",
    "src/sase/axe/run_agent_helpers.py:update_step_marker_chat_path",
    "src/sase/axe/run_agent_markers.py:write_agent_meta",
    "src/sase/axe/run_agent_retry_spawn.py:mark_parent_retried",
    "src/sase/axe/run_agent_runner_finalize.py:write_error_done_marker",
    "src/sase/axe/run_agent_runner_setup.py:setup_artifacts_directory",
    "src/sase/axe/run_agent_runner_setup.py:write_agent_meta",
    "src/sase/axe/run_agent_runner_setup.py:write_home_running_marker",
    "src/sase/axe/run_agent_wait.py:wait_for_dependencies",
    "src/sase/axe/run_workflow_runner.py:_write_workflow_state",
    "src/sase/axe/runner_utils.py:write_agent_meta",
    "src/sase/axe/runner_utils.py:write_done_marker",
    "src/sase/integrations/_mobile_notification_side_effects.py:"
    "_persist_plan_approved_metadata",
    "src/sase/main/query_handler/_query.py:run_query",
    "src/sase/scripts/sase_chop_wait_checks.py:main",
    "src/sase/xprompt/workflow_executor.py:_save_prompt_step_marker",
    "src/sase/xprompt/workflow_executor.py:_save_state",
    "src/sase/xprompt/workflow_runner.py:_write_failed_workflow_state",
}


def _own_descendants(root: ast.AST) -> list[ast.AST]:
    descendants: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(root))
    while stack:
        node = stack.pop()
        if isinstance(node, _NESTED_SCOPE_NODES):
            continue
        descendants.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return descendants


def _contains_tracked_marker_literal(nodes: list[ast.AST]) -> bool:
    for node in nodes:
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if any(marker in node.value for marker in _TRACKED_MARKER_LITERALS):
            return True
    return False


def _is_write_mode_open(call: ast.Call) -> bool:
    for arg in call.args[1:]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            if "w" in arg.value:
                return True
    for keyword in call.keywords:
        if (
            keyword.arg == "mode"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
            and "w" in keyword.value.value
        ):
            return True
    return False


def _contains_marker_mutation_call(nodes: list[ast.AST]) -> bool:
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            if func.id == "open" and _is_write_mode_open(node):
                return True
            if func.id in _MUTATION_CALL_NAMES:
                return True
            continue
        if not isinstance(func, ast.Attribute):
            continue
        if (
            func.attr == "replace"
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
        ):
            return True
        if func.attr in _MUTATION_CALL_NAMES:
            return True
    return False


def _marker_mutation_contexts() -> set[str]:
    contexts: set[str] = set()
    for path in sorted((_REPO_ROOT / "src" / "sase").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel_path = path.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, _FUNCTION_NODES):
                continue
            descendants = _own_descendants(node)
            if not _contains_tracked_marker_literal(descendants):
                continue
            if _contains_marker_mutation_call(descendants):
                contexts.add(f"{rel_path}:{node.name}")
    return contexts


def test_tracked_marker_mutation_sites_are_reviewed() -> None:
    assert _marker_mutation_contexts() == _REVIEWED_MARKER_MUTATION_CONTEXTS
