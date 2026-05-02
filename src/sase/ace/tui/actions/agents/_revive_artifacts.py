"""Artifact-file restoration helpers for agent revival.

Reconstructs the on-disk markers (``done.json``, ``workflow_state.json``,
``prompt_step_*.json``, ``agent_meta.json``) so ``load_all_agents()``
rediscovers a revived agent identical to its original.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent


class ArtifactRestorationMixin:
    """Mixin providing artifact-file restoration for revived agents."""

    def _restore_agent_artifacts(
        self,
        agent: Agent,
        *,
        parent_artifacts_dir: str | None = None,
    ) -> None:
        """Restore artifact files so load_all_agents() rediscovers the agent.

        Writes back the full state that the loaders expect so revived agents
        appear identical to their originals in the TUI.

        For RUNNING agents: writes done.json to the artifacts directory.
        For WORKFLOW parents: writes workflow_state.json with all metadata.
        For WORKFLOW children: writes prompt_step_<idx>.json with all metadata.

        Args:
            agent: The agent whose artifacts should be restored.
            parent_artifacts_dir: For child steps, the parent workflow's
                artifacts directory (so the child marker is written alongside
                the parent's workflow_state.json).
        """
        from ...models.agent import AgentType

        project_path = Path(agent.project_file)
        project_name = project_path.parent.name

        if agent.agent_type == AgentType.RUNNING:
            timestamp = agent.extract_artifacts_timestamp()
            if not timestamp:
                return
            artifacts_dir = Path(
                os.path.expanduser(
                    f"~/.sase/projects/{project_name}/artifacts/ace-run/{timestamp}"
                )
            )
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            done_file = artifacts_dir / "done.json"
            if not done_file.exists():
                done_data = self._build_done_json_data(agent)
                done_file.write_text(json.dumps(done_data))
            self._restore_agent_meta(agent, artifacts_dir)

        elif agent.agent_type == AgentType.WORKFLOW:
            if agent.is_workflow_child:
                # Child step: write prompt_step_<idx>.json into parent's dir
                if agent.parent_timestamp is None:
                    return
                step_index = agent.step_index if agent.step_index is not None else 0
                # Use the parent's actual artifacts dir when provided,
                # so the child marker lands alongside workflow_state.json
                # (appears_as_agent workflows may use ace-run/).
                if parent_artifacts_dir:
                    artifacts_dir = Path(parent_artifacts_dir)
                else:
                    parent_workflow = agent.parent_workflow or ""
                    base_workflow = (
                        parent_workflow.split("/")[-1]
                        if "/" in parent_workflow
                        else parent_workflow
                    )
                    workflow_dir_name = f"workflow-{base_workflow}"
                    parent_ts = agent.parent_timestamp
                    if len(parent_ts) == 13 and parent_ts[6] == "_":
                        parent_ts = f"20{parent_ts[:6]}{parent_ts[7:]}"
                    artifacts_dir = Path(
                        os.path.expanduser(
                            f"~/.sase/projects/{project_name}/artifacts/{workflow_dir_name}/{parent_ts}"
                        )
                    )
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                step_file = artifacts_dir / f"prompt_step_{step_index}.json"
                if not step_file.exists():
                    step_data = self._build_step_marker_data(agent)
                    step_file.write_text(json.dumps(step_data))
                if agent.artifacts_dir:
                    self._restore_agent_meta(agent, Path(agent.artifacts_dir))
            else:
                # Parent workflow: write workflow_state.json
                # Use the agent's original artifacts_dir (from bundle) when
                # available so the marker is recreated in the same directory
                # where prompt files live.  appears_as_agent workflows may
                # store artifacts in ace-run/ instead of workflow-{name}/.
                if agent.artifacts_dir:
                    artifacts_dir = Path(agent.artifacts_dir)
                else:
                    timestamp = agent.extract_artifacts_timestamp()
                    if not timestamp:
                        return
                    workflow = agent.workflow or ""
                    base_workflow = (
                        workflow.split("/")[-1] if "/" in workflow else workflow
                    )
                    workflow_dir_name = f"workflow-{base_workflow}"
                    artifacts_dir = Path(
                        os.path.expanduser(
                            f"~/.sase/projects/{project_name}/artifacts/{workflow_dir_name}/{timestamp}"
                        )
                    )
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                state_file = artifacts_dir / "workflow_state.json"
                if not state_file.exists():
                    state_data = self._build_workflow_state_data(agent)
                    state_file.write_text(json.dumps(state_data))
                # For appears_as_agent workflows, also write done.json so the
                # RUNNING↔WORKFLOW dedup in load_all_agents() merges
                # response_path from the RUNNING entry into the WORKFLOW agent.
                if agent.appears_as_agent:
                    done_file = artifacts_dir / "done.json"
                    if not done_file.exists():
                        done_data = self._build_done_json_data(agent)
                        done_file.write_text(json.dumps(done_data))
                self._restore_agent_meta(agent, artifacts_dir)

    @staticmethod
    def _canonicalize_workflow_marker_status(status: str) -> str:
        """Map display statuses to canonical workflow_state statuses."""
        if status in {"completed", "failed", "running", "waiting_hitl"}:
            return status
        if status in {
            "DONE",
            "PLAN DONE",
            "PLAN COMMITTED",
            "PLAN REJECTED",
            "EPIC APPROVED",
            "EPIC CREATED",
        }:
            return "completed"
        if status == "FAILED":
            return "failed"
        if status in {"WAITING", "WAITING INPUT"}:
            return "waiting_hitl"
        if status in {"RUNNING", "PLANNING", "PLAN APPROVED", "QUESTION"}:
            return "running"
        return status

    @staticmethod
    def _canonicalize_step_marker_status(status: str) -> str:
        """Map display statuses to canonical prompt_step marker statuses."""
        if status in {"completed", "failed", "in_progress", "waiting_hitl"}:
            return status
        if status in {
            "DONE",
            "PLAN DONE",
            "PLAN COMMITTED",
            "PLAN REJECTED",
            "EPIC APPROVED",
            "EPIC CREATED",
        }:
            return "completed"
        if status == "FAILED":
            return "failed"
        if status in {"WAITING", "WAITING INPUT"}:
            return "waiting_hitl"
        if status in {"RUNNING", "PLANNING", "PLAN APPROVED", "QUESTION"}:
            return "in_progress"
        return status

    @staticmethod
    def _build_workflow_state_data(agent: Agent) -> dict[str, Any]:
        """Build a workflow_state.json dict from a parent workflow Agent."""
        status = agent.status or "DONE"
        data: dict[str, Any] = {
            "status": ArtifactRestorationMixin._canonicalize_workflow_marker_status(
                status
            ),
            "workflow_name": agent.workflow or "unknown",
            "context": {"cl_name": agent.cl_name},
            "appears_as_agent": agent.appears_as_agent,
            "is_anonymous": agent.is_anonymous,
        }
        if agent.start_time is not None:
            data["start_time"] = agent.start_time.isoformat()
        if agent.pid is not None:
            data["pid"] = agent.pid
        if agent.error_message:
            data["error"] = agent.error_message
        if agent.error_traceback:
            data["traceback"] = agent.error_traceback
        # Add a steps entry so the loader can extract diff_path and step_output
        if agent.step_output is not None or agent.diff_path:
            step_entry: dict[str, Any] = {
                "name": "agent",
                "status": "completed",
            }
            if agent.step_output is not None:
                step_entry["output"] = agent.step_output
            if agent.diff_path:
                if "output" not in step_entry:
                    step_entry["output"] = {}
                step_entry["output"]["diff_path"] = agent.diff_path
            data["steps"] = [step_entry]
        return data

    @staticmethod
    def _build_step_marker_data(agent: Agent) -> dict[str, Any]:
        """Build a prompt_step_*.json dict from a child workflow Agent."""
        status = agent.status or "DONE"
        data: dict[str, Any] = {
            "status": ArtifactRestorationMixin._canonicalize_step_marker_status(status),
            "workflow_name": agent.parent_workflow or agent.workflow or "unknown",
            "step_name": agent.step_name or agent.cl_name,
        }
        if agent.step_type is not None:
            data["step_type"] = agent.step_type
        if agent.step_source is not None:
            data["step_source"] = agent.step_source
        if agent.step_output is not None:
            data["output"] = agent.step_output
        if agent.step_index is not None:
            data["step_index"] = agent.step_index
        if agent.total_steps is not None:
            data["total_steps"] = agent.total_steps
        if agent.parent_step_index is not None:
            data["parent_step_index"] = agent.parent_step_index
        if agent.parent_total_steps is not None:
            data["parent_total_steps"] = agent.parent_total_steps
        if agent.is_hidden_step:
            data["hidden"] = True
        if agent.artifacts_dir:
            data["artifacts_dir"] = agent.artifacts_dir
        if agent.diff_path:
            data["diff_path"] = agent.diff_path
        if agent.error_message:
            data["error"] = agent.error_message
        if agent.error_traceback:
            data["traceback"] = agent.error_traceback
        if agent.response_path:
            data["response_path"] = agent.response_path
        if agent.embedded_workflow_name:
            data["embedded_workflow_name"] = agent.embedded_workflow_name
        if agent.is_pre_prompt_step:
            data["is_pre_prompt_step"] = True
        return data

    @staticmethod
    def _build_done_json_data(agent: Agent) -> dict[str, Any]:
        """Build a complete done.json dict from a RUNNING Agent.

        Mirrors the fields that load_done_agents() reads so revived agents
        appear identical to their originals.
        """
        if agent.status == "FAILED":
            outcome = "failed"
        elif agent.status == "PLAN REJECTED":
            outcome = "plan_rejected"
        else:
            outcome = "completed"
        data: dict[str, Any] = {
            "status": "DONE",
            "cl_name": agent.cl_name,
            "project_file": agent.project_file,
            "outcome": outcome,
        }
        if agent.response_path:
            data["response_path"] = agent.response_path
        if agent.diff_path:
            data["diff_path"] = agent.diff_path
        if agent.step_output is not None:
            data["step_output"] = agent.step_output
        if agent.workspace_num is not None:
            data["workspace_num"] = agent.workspace_num
        if agent.output_path:
            data["output_path"] = agent.output_path
        if agent.model:
            data["model"] = agent.model
        if agent.llm_provider:
            data["llm_provider"] = agent.llm_provider
        if agent.vcs_provider:
            data["vcs_provider"] = agent.vcs_provider
        if agent.agent_name:
            data["name"] = agent.agent_name
        if agent.approve:
            data["approve"] = agent.approve
        if agent.extra_files:
            data["plan_path"] = agent.extra_files[0]
        if agent.error_message:
            data["error"] = agent.error_message
        if agent.error_traceback:
            data["traceback"] = agent.error_traceback
        return data

    @staticmethod
    def _restore_agent_meta(agent: Agent, artifacts_dir: Path) -> None:
        """Write agent_meta.json if missing and agent has metadata."""
        meta_path = artifacts_dir / "agent_meta.json"
        if meta_path.exists():
            return

        data: dict[str, Any] = {}
        if agent.model:
            data["model"] = agent.model
        if agent.llm_provider:
            data["llm_provider"] = agent.llm_provider
        if agent.vcs_provider:
            data["vcs_provider"] = agent.vcs_provider
        if agent.agent_name:
            data["name"] = agent.agent_name
        if agent.waiting_for:
            data["wait_for"] = agent.waiting_for
        if agent.approve:
            data["approve"] = agent.approve
        if agent.hidden:
            data["hidden"] = True
        if agent.role_suffix:
            data["role_suffix"] = agent.role_suffix
        if agent.parent_timestamp:
            data["parent_timestamp"] = agent.parent_timestamp
        if agent.workspace_num is not None:
            data["workspace_num"] = agent.workspace_num
        if agent.response_path:
            data["chat_path"] = agent.response_path

        if agent.run_start_time is not None:
            data["run_started_at"] = agent.run_start_time.isoformat()
        if agent.stop_time is not None:
            data["stopped_at"] = agent.stop_time.isoformat()

        if agent.plan_times:
            plan_values = [ts.isoformat() for ts in agent.plan_times]
            data["plan_submitted_at"] = (
                plan_values[0] if len(plan_values) == 1 else plan_values
            )
        if agent.epic_time is not None:
            data["epic_started_at"] = agent.epic_time.isoformat()
        if agent.feedback_times:
            feedback_values = [ts.isoformat() for ts in agent.feedback_times]
            data["feedback_submitted_at"] = (
                feedback_values[0] if len(feedback_values) == 1 else feedback_values
            )
        if agent.questions_times:
            questions_values = [ts.isoformat() for ts in agent.questions_times]
            data["questions_submitted_at"] = (
                questions_values[0] if len(questions_values) == 1 else questions_values
            )
        if agent.retry_times:
            data["retry_started_at"] = [ts.isoformat() for ts in agent.retry_times]

        is_plan_like_status = agent.status in {
            "PLANNING",
            "PLAN APPROVED",
            "PLAN COMMITTED",
            "PLAN DONE",
            "PLAN REJECTED",
            "EPIC APPROVED",
            "EPIC CREATED",
            "LEGEND APPROVED",
            "QUESTION",
        }
        if agent.role_suffix == ".plan" or is_plan_like_status:
            data["plan"] = True
        if agent.status in {
            "PLAN APPROVED",
            "PLAN COMMITTED",
            "EPIC APPROVED",
            "LEGEND APPROVED",
        }:
            data["plan_approved"] = True
            if agent.status == "PLAN COMMITTED":
                data["plan_action"] = "commit"
            elif agent.status == "EPIC APPROVED":
                data["plan_action"] = "epic"
            elif agent.status == "LEGEND APPROVED":
                data["plan_action"] = "legend"

        if data:
            meta_path.write_text(json.dumps(data))
