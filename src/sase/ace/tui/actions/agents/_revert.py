"""Agents-tab action for reverting a done agent's commits (leader ``,r``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ....revert_agent import (
        BulkRevertPreview,
        BulkRevertResult,
        RevertPreview,
        RevertResult,
        RevertTarget,
    )
    from ...models import Agent
    from ...models.agent import AgentType
    from ..task_actions import TrackedTaskCompletion


class AgentRevertMixin:
    """Mixin providing the Agents-tab revert-selected-agent flow.

    The key handler stays lightweight: it captures the selected agent, gates on
    a revertable status plus a resolvable agent name and git workspace, then
    submits a tracked *preview* task. Preview completion opens
    :class:`ConfirmRevertAgentModal`; confirmation submits a tracked *revert*
    task that creates the revert commit and refreshes the Agents tab.

    When marked agents exist, ``,r`` instead reverts the combined commit set of
    every marked agent as a single atomic transaction (see
    :meth:`_start_revert_marked_agents`).
    """

    current_tab: str
    current_idx: int
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]

    def _start_revert_selected_agent(self) -> None:
        """Discover and (after confirmation) revert the selected agent's commits.

        Routes to the bulk marked-agent path when any agent marks exist;
        otherwise reverts the single selected agent.
        """
        if self.current_tab != "agents":
            return

        if getattr(self, "_marked_agents", None):
            self._start_revert_marked_agents()
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

    # ------------------------------------------------------------------
    # Bulk (marked-agent) revert
    # ------------------------------------------------------------------

    def _start_revert_marked_agents(self) -> None:
        """Revert the combined commit set of every marked agent atomically.

        Resolves live marked rows, drops stale marks, skips non-revertable and
        unresolvable rows (with feedback), rejects mixed workspaces, then
        submits one tracked bulk *preview* task.
        """
        prune = getattr(self, "_prune_stale_marked_agents", None)
        if callable(prune):
            prune()

        marked = self._marked_agents
        live = [a for a in self._agents_with_children if a.identity in marked]
        if not live:
            self.notify("No marked agents remain", severity="warning")  # type: ignore[attr-defined]
            return

        from ...models.agent_status import is_revertable_agent_status

        revertable = [a for a in live if is_revertable_agent_status(a.status)]
        skipped_non_revertable = len(live) - len(revertable)
        if not revertable:
            self.notify(  # type: ignore[attr-defined]
                "No marked agents are revertable (need done/failed)",
                severity="warning",
            )
            return

        from ....revert_agent import (
            RevertTarget,
            resolve_revert_agent_name,
            resolve_revert_family_base,
            resolve_revert_workspace_dir,
        )

        targets: list[RevertTarget] = []
        seen: set[tuple[str, str]] = set()
        representative: Agent | None = None
        unresolved = 0
        for agent in revertable:
            agent_name = resolve_revert_agent_name(agent)
            workspace_dir = resolve_revert_workspace_dir(agent)
            if not agent_name or not workspace_dir:
                unresolved += 1
                continue
            dedup = (agent_name, workspace_dir)
            if dedup in seen:
                continue
            seen.add(dedup)
            family_base = resolve_revert_family_base(agent, agent_name)
            targets.append(
                RevertTarget(
                    agent_name=agent_name,
                    display_name=agent.display_name,
                    workspace_dir=workspace_dir,
                    family_base=family_base,
                    artifacts_dir=agent.get_artifacts_dir(),
                )
            )
            if representative is None:
                representative = agent

        if not targets or representative is None:
            self.notify(  # type: ignore[attr-defined]
                "No revertable marked agents could be resolved",
                severity="warning",
            )
            return

        workspaces = {t.workspace_dir for t in targets}
        if len(workspaces) > 1:
            self.notify(  # type: ignore[attr-defined]
                "Marked agents span multiple workspaces; no changes were applied",
                severity="error",
            )
            return

        skipped = skipped_non_revertable + unresolved
        if skipped:
            self.notify(  # type: ignore[attr-defined]
                f"Skipping {skipped} marked agent(s) not eligible for revert",
                severity="warning",
            )

        self._submit_bulk_revert_preview(targets, representative)

    def _submit_bulk_revert_preview(
        self,
        targets: list[RevertTarget],
        representative: Agent,
    ) -> None:
        from ....revert_agent import preview_agents_revert
        from ..task_actions import TrackedTaskResult

        workspace_dir = targets[0].workspace_dir
        names = sorted(t.agent_name for t in targets)
        dedup_key = "revert_preview:bulk:" + ",".join(names) + ":" + workspace_dir

        def _callable() -> TrackedTaskResult[BulkRevertPreview]:
            preview = preview_agents_revert(targets)
            return TrackedTaskResult(
                success=True,
                message=preview.error
                or f"Found {preview.commit_count} commit(s) to revert",
                payload=preview,
            )

        def _on_complete(
            completion: TrackedTaskCompletion[BulkRevertPreview],
        ) -> None:
            preview = completion.payload
            if preview is None:
                self.notify(  # type: ignore[attr-defined]
                    "Bulk revert preview failed",
                    severity="error",
                )
                return
            if not preview.ok:
                self.notify(  # type: ignore[attr-defined]
                    preview.error or "No commits to revert were found",
                    severity="warning",
                )
                return
            self._open_confirm_bulk_revert_modal(preview, representative)

        self._submit_tracked_task(  # type: ignore[attr-defined]
            "revert_preview",
            representative.cl_name,
            representative.project_file,
            _callable,
            display_name=f"Revert preview: {len(targets)} marked agents",
            dedup_key=dedup_key,
            on_complete=_on_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    def _open_confirm_bulk_revert_modal(
        self,
        preview: BulkRevertPreview,
        representative: Agent,
    ) -> None:
        from ...modals import ConfirmRevertAgentModal

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self._submit_bulk_revert_execute(preview, representative)

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmRevertAgentModal(preview),
            _on_confirm,
        )

    def _submit_bulk_revert_execute(
        self,
        preview: BulkRevertPreview,
        representative: Agent,
    ) -> None:
        from ....revert_agent import execute_agents_revert
        from ..task_actions import TrackedTaskResult

        workspace_dir = preview.workspace_dir
        names = sorted(t.agent_name for t in preview.targets)
        dedup_key = "revert_agent:bulk:" + ",".join(names) + ":" + workspace_dir

        def _callable() -> TrackedTaskResult[BulkRevertResult]:
            result = execute_agents_revert(preview)
            return TrackedTaskResult(
                success=result.success,
                message=result.message,
                payload=result,
                error=result.error,
            )

        def _on_complete(
            completion: TrackedTaskCompletion[BulkRevertResult],
        ) -> None:
            if completion.success:
                self._schedule_agents_async_refresh(source="revert_agent")  # type: ignore[attr-defined]

        self._submit_tracked_task(  # type: ignore[attr-defined]
            "revert_agent",
            representative.cl_name,
            representative.project_file,
            _callable,
            display_name=f"Revert {preview.target_count} marked agents",
            dedup_key=dedup_key,
            on_complete=_on_complete,
            reload_on_complete=False,
            notify_on_complete=True,
        )
