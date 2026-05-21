"""Audit direct mutation sites for Tier 1-projected agent marker files."""

from __future__ import annotations

import ast
from dataclasses import dataclass
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
_LIFECYCLE_CALL_NAMES = {
    "update_agent_artifact_index_for_marker_mutation",
    "upsert_agent_artifact_index_artifacts",
    "delete_agent_artifact_index_artifacts",
    "sync_dismissed_agent_artifact_index",
}
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_NESTED_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclass(frozen=True)
class BatchedCoverage:
    """A helper mutates markers and a known caller refreshes the index in batch."""

    caller_context: str
    helper_call: str
    lifecycle_call: str


@dataclass(frozen=True)
class DelegatedCoverage:
    """A context delegates marker mutation to another reviewed helper/context."""

    caller_context: str
    helper_call: str
    coverage_context: str


@dataclass(frozen=True)
class Review:
    """Expected mutation shape and lifecycle coverage for one mutation context."""

    mutation_calls: tuple[str, ...]
    lifecycle_calls: tuple[str, ...] = ()
    batched_by: tuple[BatchedCoverage, ...] = ()
    delegated: DelegatedCoverage | None = None
    exemption: str = ""


@dataclass(frozen=True)
class ContextInfo:
    """Observed audit details for one marker mutation context."""

    mutation_calls: tuple[str, ...]
    lifecycle_calls: tuple[str, ...]


_UPDATE_INDEX = "update_agent_artifact_index_for_marker_mutation"
_UPSERT_INDEX = "upsert_agent_artifact_index_artifacts"
_DELETE_INDEX = "delete_agent_artifact_index_artifacts"

_REVIEWED_MARKER_MUTATION_CONTEXTS: dict[str, Review] = {
    "src/sase/ace/tui/actions/agents/_approve.py:_persist_plan_auto_approval": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/ace/tui/actions/agents/_killing_utils.py:delete_agent_artifacts": Review(
        mutation_calls=("unlink",),
        lifecycle_calls=(_DELETE_INDEX,),
    ),
    (
        "src/sase/ace/tui/actions/agents/_notification_plan_persistence.py:"
        "persist_plan_approved"
    ): Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    (
        "src/sase/ace/tui/actions/agents/_revive_artifacts.py:_restore_agent_artifacts"
    ): Review(
        mutation_calls=("write_text", "write_text", "write_text", "write_text"),
        batched_by=(
            BatchedCoverage(
                caller_context=(
                    "src/sase/ace/tui/actions/agents/_revive.py:_do_revive_agent"
                ),
                helper_call="_restore_agent_artifacts",
                lifecycle_call=_UPSERT_INDEX,
            ),
            BatchedCoverage(
                caller_context=(
                    "src/sase/ace/tui/actions/agents/_revive.py:_do_revive_agents"
                ),
                helper_call="_restore_agent_artifacts",
                lifecycle_call=_UPSERT_INDEX,
            ),
        ),
    ),
    "src/sase/ace/tui/actions/agents/_revive_artifacts.py:_restore_agent_meta": Review(
        mutation_calls=("write_text",),
        delegated=DelegatedCoverage(
            caller_context=(
                "src/sase/ace/tui/actions/agents/_revive_artifacts.py:"
                "_restore_agent_artifacts"
            ),
            helper_call="_restore_agent_meta",
            coverage_context=(
                "src/sase/ace/tui/actions/agents/_revive_artifacts.py:"
                "_restore_agent_artifacts"
            ),
        ),
    ),
    "src/sase/ace/tui/actions/agents/_wait_resume.py:_apply_wait": Review(
        mutation_calls=("open", "dump", "open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/ace/tui/actions/rename.py:handle_name_result": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    (
        "src/sase/ace/tui/models/_loaders/_running_loaders.py:"
        "load_running_home_agents_from_snapshot"
    ): Review(
        mutation_calls=("unlink",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    (
        "src/sase/ace/tui/models/_loaders/_running_loaders.py:load_running_home_agents"
    ): Review(
        mutation_calls=("unlink",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/agent/names/_migration.py:_rewrite_artifact_json_files": Review(
        mutation_calls=("_write_json_file", "_write_json_file"),
        batched_by=(
            BatchedCoverage(
                caller_context=(
                    "src/sase/agent/names/_migration.py:"
                    "run_historical_auto_name_migration"
                ),
                helper_call="_rewrite_artifact_json_files",
                lifecycle_call=_UPSERT_INDEX,
            ),
        ),
    ),
    "src/sase/agent/names/_wipe.py:_release_artifact_workspace": Review(
        mutation_calls=("unlink",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/agent/running.py:kill_named_agent": Review(
        mutation_calls=("unlink",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_directives.py:extract_directives_and_write_meta": Review(
        mutation_calls=("unlink",),
        delegated=DelegatedCoverage(
            caller_context=(
                "src/sase/axe/run_agent_directives.py:extract_directives_and_write_meta"
            ),
            helper_call="write_agent_meta",
            coverage_context="src/sase/axe/run_agent_markers.py:write_agent_meta",
        ),
    ),
    "src/sase/axe/run_agent_exec_markers.py:write_done_marker_and_update_index": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_exec_markers.py:update_workflow_pdf_status": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_exec_markers.py:clear_workflow_pdf_activity": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_exec_plan_artifacts.py:write_plan_path_artifact": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers.py:append_meta_list_field": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers.py:update_meta_field": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers.py:update_meta_suffix": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers.py:promote_to_workflow": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers.py:normalize_handoff_interruption_state": Review(
        mutation_calls=("open", "dump", "open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers.py:update_step_marker_chat_path": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers.py:create_followup_artifacts": Review(
        mutation_calls=("open", "dump", "open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers.py:handle_questions_flow": Review(
        mutation_calls=("open", "dump", "open", "dump", "unlink"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_markers.py:write_agent_meta": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_retry_spawn.py:mark_parent_retried": Review(
        mutation_calls=("write_text",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_runner_finalize.py:write_error_done_marker": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_runner_setup.py:setup_artifacts_directory": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_runner_setup.py:write_agent_meta": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_runner_setup.py:write_home_running_marker": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_wait.py:wait_for_dependencies": Review(
        mutation_calls=(
            "open",
            "dump",
            "unlink",
            "open",
            "dump",
            "unlink",
            "open",
            "dump",
            "unlink",
        ),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_workflow_runner.py:_write_workflow_state": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/runner_utils.py:write_agent_meta": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/runner_utils.py:write_done_marker": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    (
        "src/sase/integrations/_mobile_notification_side_effects.py:"
        "_persist_plan_approved_metadata"
    ): Review(
        mutation_calls=("write_text",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/main/query_handler/_query.py:run_query": Review(
        mutation_calls=(
            "open",
            "open",
            "dump",
            "open",
            "dump",
            "open",
            "open",
            "dump",
        ),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/scripts/sase_chop_wait_checks.py:main": Review(
        mutation_calls=("open", "dump"),
        exemption=(
            "Writes ready.json only; waiting.json and agent_meta.json are read "
            "inputs, and ready.json is not Tier 1 indexed."
        ),
    ),
    "src/sase/xprompt/workflow_executor.py:_save_state": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/xprompt/workflow_executor.py:_save_prompt_step_marker": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/xprompt/workflow_runner.py:_write_failed_workflow_state": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
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


def _generic_call_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _mutation_call_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        if func.id == "open" and _is_write_mode_open(call):
            return "open"
        if func.id in _MUTATION_CALL_NAMES:
            return func.id
        return None
    if not isinstance(func, ast.Attribute):
        return None
    if (
        func.attr == "replace"
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
    ):
        return "os.replace"
    if func.attr in _MUTATION_CALL_NAMES:
        return func.attr
    return None


def _lifecycle_call_name(call: ast.Call) -> str | None:
    name = _generic_call_name(call)
    if name in _LIFECYCLE_CALL_NAMES:
        return name
    return None


def _source_ordered_calls(nodes: list[ast.AST]) -> list[ast.Call]:
    calls = [node for node in nodes if isinstance(node, ast.Call)]
    return sorted(
        calls,
        key=lambda call: (
            getattr(call, "lineno", 0),
            getattr(call, "col_offset", 0),
        ),
    )


def _contains_marker_mutation_call(nodes: list[ast.AST]) -> bool:
    return any(_mutation_call_name(call) for call in _source_ordered_calls(nodes))


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _context_node(context: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    rel_path, name = context.split(":", 1)
    path = _REPO_ROOT / rel_path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, _FUNCTION_NODES) and node.name == name:
            return node
    raise AssertionError(f"missing context {context}")


def _context_call_names(context: str) -> tuple[str, ...]:
    node = _context_node(context)
    calls = (
        _generic_call_name(call)
        for call in _source_ordered_calls(_own_descendants(node))
    )
    return tuple(name for name in calls if name is not None)


def _marker_mutation_contexts() -> dict[str, ContextInfo]:
    contexts: dict[str, ContextInfo] = {}
    for path in sorted((_REPO_ROOT / "src" / "sase").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel_path = path.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, _FUNCTION_NODES):
                continue
            descendants = _own_descendants(node)
            if not _contains_tracked_marker_literal(descendants):
                continue
            if not _contains_marker_mutation_call(descendants):
                continue
            mutation_calls = tuple(
                name
                for call in _source_ordered_calls(descendants)
                if (name := _mutation_call_name(call)) is not None
            )
            lifecycle_calls = tuple(
                name
                for call in _source_ordered_calls(descendants)
                if (name := _lifecycle_call_name(call)) is not None
            )
            contexts[f"{rel_path}:{node.name}"] = ContextInfo(
                mutation_calls=mutation_calls,
                lifecycle_calls=_unique(lifecycle_calls),
            )
    return contexts


def _has_lifecycle_coverage(review: Review) -> bool:
    return bool(review.lifecycle_calls or review.batched_by or review.delegated)


def test_tracked_marker_mutation_sites_are_reviewed() -> None:
    assert set(_marker_mutation_contexts()) == set(_REVIEWED_MARKER_MUTATION_CONTEXTS)


def test_reviewed_marker_mutation_sites_match_expected_mutations() -> None:
    contexts = _marker_mutation_contexts()
    expected = {
        context: review.mutation_calls
        for context, review in _REVIEWED_MARKER_MUTATION_CONTEXTS.items()
    }
    actual = {
        context: info.mutation_calls
        for context, info in contexts.items()
        if context in _REVIEWED_MARKER_MUTATION_CONTEXTS
    }
    assert actual == expected


def test_reviewed_marker_mutation_sites_declare_lifecycle_coverage() -> None:
    contexts = _marker_mutation_contexts()
    for context, review in _REVIEWED_MARKER_MUTATION_CONTEXTS.items():
        coverage_kinds = sum(
            bool(kind)
            for kind in (
                review.lifecycle_calls,
                review.batched_by,
                review.delegated,
                review.exemption,
            )
        )
        assert coverage_kinds == 1, context

        if review.lifecycle_calls:
            missing = set(review.lifecycle_calls) - set(
                contexts[context].lifecycle_calls
            )
            assert not missing, f"{context} is missing lifecycle calls: {missing}"

        for coverage in review.batched_by:
            caller_calls = _context_call_names(coverage.caller_context)
            assert coverage.helper_call in caller_calls, coverage
            assert coverage.lifecycle_call in caller_calls, coverage

        if review.delegated is not None:
            caller_calls = _context_call_names(review.delegated.caller_context)
            assert review.delegated.helper_call in caller_calls, review.delegated
            coverage_review = _REVIEWED_MARKER_MUTATION_CONTEXTS[
                review.delegated.coverage_context
            ]
            assert _has_lifecycle_coverage(coverage_review), review.delegated

        if review.exemption:
            assert review.exemption.strip(), context
