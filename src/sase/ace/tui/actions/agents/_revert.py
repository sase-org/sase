"""Agents-tab action for reverting a done agent's commits (leader ``,r``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ....revert_agent import RevertPreview, RevertResult
    from ...models import Agent
    from ..task_actions import TrackedTaskCompletion


class AgentRevertMixin:
    """Mixin providing the Agents-tab revert-selected-agent flow.

    The key handler stays lightweight: it captures the selected agent, gates on
    a revertable status plus a resolvable agent name and git workspace, then
    submits a tracked *preview* task. Preview completion opens
    :class:`ConfirmRevertAgentModal`; confirmation submits a tracked *revert*
    task that creates the revert commit and refreshes the Agents tab.
    """

    current_tab: str
    current_idx: int
    _agents: list[Agent]

    def _start_revert_selected_agent(self) -> None:
        """Discover and (after confirmation) revert the selected agent's commits."""
        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        from ...models.agent_status import is_revertable_agent_status

        if not is_revertable_agent_status(agent.status):
            self.notify(  # type: ignore[attr-defined]
                "Revert needs a done or failed agent",
                severity="warning",
            )
            return

        from ....revert_agent import (
            resolve_revert_agent_name,
            resolve_revert_family_base,
            resolve_revert_workspace_dir,
        )

        agent_name = resolve_revert_agent_name(agent)
        if not agent_name:
            self.notify(  # type: ignore[attr-defined]
                "Could not resolve an agent name for revert",
                severity="warning",
            )
            return

        workspace_dir = resolve_revert_workspace_dir(agent)
        if not workspace_dir:
            self.notify(  # type: ignore[attr-defined]
                "No workspace directory for agent",
                severity="warning",
            )
            return

        family_base = resolve_revert_family_base(agent, agent_name)
        self._submit_revert_preview(agent, agent_name, workspace_dir, family_base)

    def _submit_revert_preview(
        self,
        agent: Agent,
        agent_name: str,
        workspace_dir: str,
        family_base: str | None,
    ) -> None:
        from ....revert_agent import preview_agent_revert
        from ..task_actions import TrackedTaskResult

        artifacts_dir = agent.get_artifacts_dir()

        def _callable() -> TrackedTaskResult[RevertPreview]:
            preview = preview_agent_revert(
                workspace_dir, agent_name, family_base=family_base
            )
            return TrackedTaskResult(
                success=True,
                message=preview.error
                or f"Found {preview.commit_count} commit(s) to revert",
                payload=preview,
            )

        def _on_complete(completion: TrackedTaskCompletion[RevertPreview]) -> None:
            preview = completion.payload
            if preview is None:
                self.notify(  # type: ignore[attr-defined]
                    "Revert preview failed",
                    severity="error",
                )
                return
            if not preview.ok:
                self.notify(  # type: ignore[attr-defined]
                    preview.error or "No commits to revert were found",
                    severity="warning",
                )
                return
            self._open_confirm_revert_modal(preview, agent, artifacts_dir)

        self._submit_tracked_task(  # type: ignore[attr-defined]
            "revert_preview",
            agent.cl_name,
            agent.project_file,
            _callable,
            display_name=f"Revert preview: {agent_name}",
            dedup_key=f"revert_preview:{agent_name}:{workspace_dir}",
            on_complete=_on_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    def _open_confirm_revert_modal(
        self,
        preview: RevertPreview,
        agent: Agent,
        artifacts_dir: str | None,
    ) -> None:
        from ...modals import ConfirmRevertAgentModal

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self._submit_revert_execute(preview, agent, artifacts_dir)

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmRevertAgentModal(preview),
            _on_confirm,
        )

    def _submit_revert_execute(
        self,
        preview: RevertPreview,
        agent: Agent,
        artifacts_dir: str | None,
    ) -> None:
        from ....revert_agent import execute_agent_revert
        from ..task_actions import TrackedTaskResult

        agent_name = preview.agent_name
        workspace_dir = preview.workspace_dir
        shas = tuple(commit.full_sha for commit in preview.commits)

        def _callable() -> TrackedTaskResult[RevertResult]:
            result = execute_agent_revert(
                workspace_dir,
                shas,
                agent_name=agent_name,
                artifacts_dir=artifacts_dir,
            )
            return TrackedTaskResult(
                success=result.success,
                message=result.message,
                payload=result,
                error=result.error,
            )

        def _on_complete(completion: TrackedTaskCompletion[RevertResult]) -> None:
            if completion.success:
                self._schedule_agents_async_refresh(source="revert_agent")  # type: ignore[attr-defined]

        self._submit_tracked_task(  # type: ignore[attr-defined]
            "revert_agent",
            agent.cl_name,
            agent.project_file,
            _callable,
            display_name=f"Revert agent: {agent_name}",
            dedup_key=f"revert_agent:{agent_name}:{workspace_dir}",
            on_complete=_on_complete,
            reload_on_complete=False,
            notify_on_complete=True,
        )
