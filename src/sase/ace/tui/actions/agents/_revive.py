"""Agent revival methods for the ace TUI app."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


def _is_child_of(child: Agent, parent: Agent) -> bool:
    """Check if *child* is a workflow step, follow-up, or retry of *parent*.

    Matches workflow step children (``parent_workflow`` set), follow-up
    agents like ``.code`` / ``.q`` (``parent_timestamp`` set,
    ``parent_workflow`` is None), and spawn-on-retry children
    (``retry_of_timestamp`` set).
    """
    # Spawn-on-retry: retry children link to the failing parent via
    # retry_of_timestamp (they are otherwise top-level RUNNING agents).
    if (
        child.retry_of_timestamp
        and parent.raw_suffix
        and child.retry_of_timestamp == parent.raw_suffix
    ):
        return True
    if not child.is_workflow_child or child.parent_timestamp != parent.raw_suffix:
        return False
    # Workflow step children have parent_workflow set; follow-up agents don't.
    return child.parent_workflow is None or child.parent_workflow == parent.workflow


class AgentRevivalMixin:
    """Mixin providing agent revival (un-dismiss) functionality.

    Overrides action_start_rewind to dispatch to revive flow when on the
    Agents tab, otherwise delegates to the original rewind behavior.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: str
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]

    def _remove_dismissed_aliases_for_suffixes(self, suffixes: set[str]) -> None:
        """Remove dismissed identities whose raw_suffix matches revived suffixes.

        Loader suppression uses suffix-based matching in addition to exact
        identity checks. Revive must clear all aliases sharing revived suffixes
        so restored artifacts can reappear in the panel.
        """
        if not suffixes:
            return
        self._dismissed_agents = {
            identity
            for identity in self._dismissed_agents
            if identity[2] is None or identity[2] not in suffixes
        }

    def action_start_rewind(self) -> None:
        """Dispatch R key: revive on Agents tab, rewind on ChangeSpecs tab."""
        if self.current_tab == "agents":
            self._revive_agent()
        else:
            super().action_start_rewind()  # type: ignore[misc]

    def _revive_agent(self) -> None:
        """Show project selection modal, then dismissed agent selection."""
        from ...modals import ProjectSelectModal, ProjectSelectResult, SelectionItem

        if not self._dismissed_agent_objects:
            self.notify("No dismissed agents to revive")  # type: ignore[attr-defined]
            return

        def _on_project_selected(result: ProjectSelectResult | None) -> None:
            if result is None:
                return
            selection = result.selection
            if not isinstance(selection, SelectionItem):
                return
            self._show_dismissed_agents_for_scope(selection)

        self.app.push_screen(  # type: ignore[attr-defined]
            ProjectSelectModal(include_all=True), _on_project_selected
        )

    def _show_dismissed_agents_for_scope(self, selection: object) -> None:
        """Filter dismissed agents by scope and show the selection modal."""
        from ...modals import SelectionItem
        from ...modals.revive_agent_modal import DismissedAgentSelectModal

        if not isinstance(selection, SelectionItem):
            return

        agents = self._dismissed_agent_objects

        if selection.item_type == "all":
            filtered = list(agents)
        elif selection.item_type == "home":
            filtered = [a for a in agents if a.cl_name == "~"]
        elif selection.item_type == "project":
            filtered = [
                a
                for a in agents
                if Path(a.project_file).parent.name == selection.project_name
            ]
        elif selection.item_type == "cl":
            filtered = [a for a in agents if a.cl_name == selection.cl_name]
        else:
            return

        # Sort: project-level agents first, then by CL name, then most recent first
        filtered.sort(
            key=lambda a: (
                0 if a.is_project_agent else 1,
                a.cl_name,
                float("inf") if a.start_time is None else -a.start_time.timestamp(),
            )
        )

        # Only show top-level DONE entries (no child steps)
        all_in_scope = list(filtered)
        filtered = [a for a in filtered if not a.is_workflow_child]

        if not filtered:
            self.notify("No dismissed agents in this scope")  # type: ignore[attr-defined]
            return

        def _on_agents_selected(agents: object) -> None:
            if agents is None:
                return
            if not isinstance(agents, list) or not agents:
                return
            if len(agents) == 1:
                self._do_revive_agent(agents[0])
            else:
                self._do_revive_agents(agents)  # type: ignore[attr-defined]

        self.app.push_screen(  # type: ignore[attr-defined]
            DismissedAgentSelectModal(filtered, all_dismissed=all_in_scope),
            _on_agents_selected,
        )

    def _do_revive_agent(self, agent: object) -> None:
        """Revive a dismissed agent by removing it from the dismissed set."""
        from ....dismissed_agents import (
            remove_bundle_by_identity,
            save_dismissed_agents,
        )
        from ...models import Agent

        if not isinstance(agent, Agent):
            return

        self._dismissed_agents.discard(agent.identity)
        revived_suffixes: set[str] = set()
        if agent.raw_suffix:
            revived_suffixes.add(agent.raw_suffix)

        # Also revive child steps and follow-up agents (e.g. .code, .q)
        child_raw_suffixes: set[str] = set()
        if not agent.is_workflow_child and agent.raw_suffix:
            for dismissed_agent in list(self._dismissed_agent_objects):
                if _is_child_of(dismissed_agent, agent):
                    self._dismissed_agents.discard(dismissed_agent.identity)
                    if dismissed_agent.raw_suffix:
                        child_raw_suffixes.add(dismissed_agent.raw_suffix)
                        revived_suffixes.add(dismissed_agent.raw_suffix)

        # Remove all dismissed aliases that share revived suffixes.
        self._remove_dismissed_aliases_for_suffixes(revived_suffixes)

        save_dismissed_agents(self._dismissed_agents)

        # Restore minimal artifact files so load_all_agents() rediscovers the agent
        self._restore_agent_artifacts(agent)

        # Also restore child step / follow-up artifacts for workflow parents
        if not agent.is_workflow_child and agent.raw_suffix:
            for dismissed_agent in list(self._dismissed_agent_objects):
                if _is_child_of(dismissed_agent, agent):
                    self._restore_agent_artifacts(
                        dismissed_agent,
                        parent_artifacts_dir=agent.artifacts_dir,
                    )

        # Clean up the bundle now that artifacts are restored
        remove_bundle_by_identity(agent.identity, child_raw_suffixes=child_raw_suffixes)

        self.notify(f"Revived agent for {agent.cl_name}")  # type: ignore[attr-defined]
        self._load_agents()  # type: ignore[attr-defined]

        # Auto-select the revived agent in the list
        if self.current_tab == "agents":
            for idx, a in enumerate(self._agents):  # type: ignore[attr-defined]
                if a.identity == agent.identity or (
                    agent.raw_suffix and a.raw_suffix == agent.raw_suffix
                ):
                    self.current_idx = idx  # type: ignore[attr-defined]
                    self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
                    break

    def _do_revive_agents(self, agents: list[Agent]) -> None:
        """Revive multiple dismissed agents in a single batch.

        Batches disk operations for efficiency: one save_dismissed_agents()
        call and one _load_agents() call instead of N each.
        """
        from ....dismissed_agents import (
            remove_bundle_by_identity,
            save_dismissed_agents,
        )
        from ...models import Agent as AgentModel

        valid_agents = [a for a in agents if isinstance(a, AgentModel)]
        if not valid_agents:
            return

        # Phase 1: Remove all from dismissed set (including children/follow-ups)
        # and collect child suffixes for bundle removal
        child_suffixes_map: dict[tuple[AgentType, str, str | None], set[str]] = {}
        revived_suffixes: set[str] = set()
        for agent in valid_agents:
            self._dismissed_agents.discard(agent.identity)
            if agent.raw_suffix:
                revived_suffixes.add(agent.raw_suffix)
            child_suffixes: set[str] = set()
            if not agent.is_workflow_child and agent.raw_suffix:
                for dismissed_agent in list(self._dismissed_agent_objects):
                    if _is_child_of(dismissed_agent, agent):
                        self._dismissed_agents.discard(dismissed_agent.identity)
                        if dismissed_agent.raw_suffix:
                            child_suffixes.add(dismissed_agent.raw_suffix)
                            revived_suffixes.add(dismissed_agent.raw_suffix)
            child_suffixes_map[agent.identity] = child_suffixes

        # Remove all dismissed aliases that share revived suffixes.
        self._remove_dismissed_aliases_for_suffixes(revived_suffixes)

        # Phase 2: Single disk write for dismissed set
        save_dismissed_agents(self._dismissed_agents)

        # Phase 3: Restore artifacts and clean bundles
        for agent in valid_agents:
            self._restore_agent_artifacts(agent)
            if not agent.is_workflow_child and agent.raw_suffix:
                for dismissed_agent in list(self._dismissed_agent_objects):
                    if _is_child_of(dismissed_agent, agent):
                        self._restore_agent_artifacts(
                            dismissed_agent,
                            parent_artifacts_dir=agent.artifacts_dir,
                        )
            remove_bundle_by_identity(
                agent.identity,
                child_raw_suffixes=child_suffixes_map.get(agent.identity),
            )

        # Phase 4: Single notification and refresh
        count = len(valid_agents)
        self.notify(f"Revived {count} agent{'s' if count != 1 else ''}")  # type: ignore[attr-defined]
        self._load_agents()  # type: ignore[attr-defined]

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
            "status": AgentRevivalMixin._canonicalize_workflow_marker_status(status),
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
            "status": AgentRevivalMixin._canonicalize_step_marker_status(status),
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
        outcome = "failed" if agent.status == "FAILED" else "completed"
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
            "EPIC APPROVED",
            "EPIC CREATED",
            "QUESTION",
        }
        if agent.role_suffix == ".plan" or is_plan_like_status:
            data["plan"] = True
        if agent.status in {"PLAN APPROVED", "PLAN COMMITTED", "EPIC APPROVED"}:
            data["plan_approved"] = True
            if agent.status == "PLAN COMMITTED":
                data["plan_action"] = "commit"
            elif agent.status == "EPIC APPROVED":
                data["plan_action"] = "epic"

        if data:
            meta_path.write_text(json.dumps(data))
