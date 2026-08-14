"""Compatibility facade for agent runner helper utilities.

The implementation is split by responsibility:
- ``run_agent_helpers_state`` handles workflow output extraction.
- ``run_agent_helpers_artifacts`` handles metadata and follow-up artifacts.
- ``run_agent_helpers_handoff`` handles handoff marker normalization.
- ``run_agent_helpers_questions`` handles user questions and Q&A prompt text.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sase.artifacts import create_artifacts_directory
from sase.axe import run_agent_helpers_artifacts as _artifacts
from sase.axe import run_agent_helpers_handoff as _handoff
from sase.axe import run_agent_helpers_questions as _questions
from sase.axe import run_agent_helpers_state as _state
from sase.axe.runner_signals import was_killed
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.main.feedback_prompt import assemble_feedback_replan_prompt
from sase.main.qa_prompt import assemble_question_followup_prompt
from sase.plan_chain import PLAN_CHAIN_PLAN_SUFFIX

if TYPE_CHECKING:
    from sase.main.qa_markdown import QARound

__all__ = [
    "append_meta_list_field",
    "assemble_feedback_replan_prompt",
    "assemble_question_followup_prompt",
    "build_qa_round",
    "create_followup_artifacts",
    "extract_step_output_and_diff_path",
    "finalize_handoff_artifacts_as_completed",
    "handle_questions_flow",
    "is_workflow_noop",
    "merge_qa_for_prompt",
    "normalize_handoff_interruption_state",
    "promote_to_workflow",
    "read_and_delete_marker",
    "read_commit_result_metadata",
    "read_commit_results_metadata",
    "update_meta_field",
    "update_meta_fields",
    "update_meta_suffix",
    "update_step_marker_chat_path",
]


def _sync_patchable_dependencies() -> None:
    """Honor legacy monkeypatches applied to this facade module."""
    _artifacts.create_artifacts_directory = create_artifacts_directory
    _artifacts.update_agent_artifact_index_for_marker_mutation = (
        update_agent_artifact_index_for_marker_mutation
    )
    _handoff.update_agent_artifact_index_for_marker_mutation = (
        update_agent_artifact_index_for_marker_mutation
    )
    _questions.update_agent_artifact_index_for_marker_mutation = (
        update_agent_artifact_index_for_marker_mutation
    )
    _questions.was_killed = was_killed


def is_workflow_noop(artifacts_dir: str) -> bool:
    return _state.is_workflow_noop(artifacts_dir)


def read_commit_result_metadata(artifacts_dir: str | None) -> dict[str, str]:
    return _state.read_commit_result_metadata(artifacts_dir)


def read_commit_results_metadata(artifacts_dir: str | None) -> list[dict[str, str]]:
    return _state.read_commit_results_metadata(artifacts_dir)


def extract_step_output_and_diff_path(
    artifacts_dir: str,
) -> tuple[dict[str, Any] | None, str | None]:
    return _state.extract_step_output_and_diff_path(artifacts_dir)


def read_and_delete_marker(artifacts_dir: str, filename: str) -> dict[str, Any] | None:
    return _state.read_and_delete_marker(artifacts_dir, filename)


def append_meta_list_field(artifacts_dir: str, key: str, value: Any) -> None:
    _sync_patchable_dependencies()
    _artifacts.append_meta_list_field(artifacts_dir, key, value)


def update_meta_field(artifacts_dir: str, key: str, value: Any) -> None:
    _sync_patchable_dependencies()
    _artifacts.update_meta_field(artifacts_dir, key, value)


def update_meta_fields(artifacts_dir: str, fields: dict[str, Any]) -> None:
    _sync_patchable_dependencies()
    _artifacts.update_meta_fields(artifacts_dir, fields)


def update_meta_suffix(artifacts_dir: str, suffix: str) -> None:
    _sync_patchable_dependencies()
    _artifacts.update_meta_suffix(artifacts_dir, suffix)


def promote_to_workflow(
    artifacts_dir: str,
    base_name: str,
    role_suffix: str = PLAN_CHAIN_PLAN_SUFFIX,
) -> None:
    _sync_patchable_dependencies()
    _artifacts.promote_to_workflow(artifacts_dir, base_name, role_suffix)


def normalize_handoff_interruption_state(artifacts_dir: str) -> None:
    _sync_patchable_dependencies()
    _handoff.normalize_handoff_interruption_state(artifacts_dir)


def finalize_handoff_artifacts_as_completed(artifacts_dir: str) -> None:
    _sync_patchable_dependencies()
    _handoff.finalize_handoff_artifacts_as_completed(artifacts_dir)


def update_step_marker_chat_path(artifacts_dir: str, chat_path: str) -> None:
    _sync_patchable_dependencies()
    _handoff.update_step_marker_chat_path(artifacts_dir, chat_path)


def create_followup_artifacts(
    project_name: str,
    base_meta: dict[str, Any],
    suffix: str,
    prev_artifacts_timestamp: str,
    *,
    workspace_num: int | None = None,
    agent_name_override: str | None = None,
    workflow_name: str | None = None,
    agent_family_role: str | None = None,
    relationships: dict[str, Any] | None = None,
) -> str:
    _sync_patchable_dependencies()
    return _artifacts.create_followup_artifacts(
        project_name,
        base_meta,
        suffix,
        prev_artifacts_timestamp,
        workspace_num=workspace_num,
        agent_name_override=agent_name_override,
        workflow_name=workflow_name,
        agent_family_role=agent_family_role,
        relationships=relationships,
    )


def handle_questions_flow(
    questions: list[dict[str, Any]],
    artifacts_dir: str,
    *,
    reacquire_runner_slot: Callable[[Callable[[], str]], str] | None = None,
    run_started_at: str | None = None,
) -> dict[str, Any] | None:
    _sync_patchable_dependencies()
    return _questions.handle_questions_flow(
        questions,
        artifacts_dir,
        reacquire_runner_slot=reacquire_runner_slot,
        run_started_at=run_started_at,
    )


def build_qa_round(
    questions: list[dict[str, Any]],
    response: dict[str, Any],
) -> QARound:
    return _questions.build_qa_round(questions, response)


def merge_qa_for_prompt(rounds: list[QARound]) -> str:
    return _questions.merge_qa_for_prompt(rounds)
