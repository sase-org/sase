"""Agents-tab action for reverting a done agent's commits (leader ``,r``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ....revert_agent import (
        BulkRevertIntent,
        BulkRevertPreview,
        BulkRevertResult,
        RevertIntent,
        RevertPreview,
        RevertResult,
        RevertTarget,
    )
    from ...models import Agent
    from ...models.agent import AgentType
    from ..proc_actions import TrackedProcCompletion


class AgentRevertMixin:
    """Mixin providing the Agents-tab revert-selected-agent flow.

    The key handler stays lightweight: it captures the selected agent, gates on
    a revertable status plus a resolvable agent name and git workspace, builds a
    :class:`RevertIntent`, then submits a tracked *preview* task. The preview and
    execute backends each claim a fresh short-lived workspace, prepare it on the
    Patch branch, and release it — they never reuse the directory the agent
    originally ran in. Preview completion opens :class:`ConfirmRevertAgentModal`;
    confirmation submits a tracked *revert* task that creates the revert commit
    and refreshes the Agents tab.

    When marked agents exist, ``,r`` instead reverts the combined commit set of
    every marked agent, one transaction per repository (see
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
            build_revert_intent,
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

        if not resolve_revert_workspace_dir(agent):
            self.notify(  # type: ignore[attr-defined]
                "No workspace directory for agent",
                severity="warning",
            )
            return

        family_base = resolve_revert_family_base(agent, agent_name)
        intent = build_revert_intent(agent, agent_name, family_base)
        self._submit_revert_preview(agent, intent)

    def _submit_revert_preview(self, agent: Agent, intent: RevertIntent) -> None:
        from ....revert_agent import preview_agent_revert_intent
        from ..proc_actions import TrackedProcResult

        def _callable() -> TrackedProcResult[RevertPreview]:
            preview = preview_agent_revert_intent(intent)
            return TrackedProcResult(
                success=True,
                message=preview.error
                or f"Found {preview.commit_count} commit(s) to revert",
                payload=preview,
            )

        def _on_complete(completion: TrackedProcCompletion[RevertPreview]) -> None:
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
            self._open_confirm_revert_modal(preview, agent, intent.artifacts_dir)

        self._submit_tracked_proc(  # type: ignore[attr-defined]
            "revert_preview",
            agent.cl_name,
            agent.project_file,
            _callable,
            display_name=f"Revert preview: {intent.agent_name}",
            dedup_key=_revert_dedup_key("revert_preview", intent),
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
        from ....revert_agent import (
            build_revert_execute_intent,
            execute_agent_revert_intent,
        )
        from ..proc_actions import TrackedProcResult

        intent = build_revert_execute_intent(agent, preview, artifacts_dir)
        agent_name = preview.agent_name

        def _callable() -> TrackedProcResult[RevertResult]:
            result = execute_agent_revert_intent(preview, intent)
            return TrackedProcResult(
                success=result.success,
                message=result.message,
                payload=result,
                error=result.error,
            )

        def _on_complete(completion: TrackedProcCompletion[RevertResult]) -> None:
            # Refresh on success or when a local revert commit was created even
            # though the post-commit push failed (the worktree state changed).
            payload = completion.payload
            if completion.success or (payload is not None and payload.reverted_shas):
                self._schedule_agents_async_refresh(source="revert_agent")  # type: ignore[attr-defined]

        self._submit_tracked_proc(  # type: ignore[attr-defined]
            "revert_agent",
            agent.cl_name,
            agent.project_file,
            _callable,
            display_name=f"Revert agent: {agent_name}",
            dedup_key=_revert_dedup_key("revert_agent", intent),
            on_complete=_on_complete,
            reload_on_complete=False,
            notify_on_complete=True,
        )

    # ------------------------------------------------------------------
    # Bulk (marked-agent) revert
    # ------------------------------------------------------------------

    def _start_revert_marked_agents(self) -> None:
        """Revert the combined commit set of every marked agent.

        Resolves live marked rows, drops stale marks, skips non-revertable and
        unresolvable rows (with feedback), rejects mixed workspaces and mixed
        Patch branches (a fresh checkout can only represent one branch),
        then submits one tracked bulk *preview* task.
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
            build_bulk_revert_intent,
            resolve_revert_agent_name,
            resolve_revert_family_base,
            resolve_revert_workspace_dir,
        )

        targets: list[RevertTarget] = []
        target_agents: list[Agent] = []
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
            target_agents.append(agent)
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

        branches = {(a.project_file, a.cl_name) for a in target_agents}
        if len(branches) > 1:
            self.notify(  # type: ignore[attr-defined]
                "Marked agents span multiple Patch branches; no changes were applied",
                severity="error",
            )
            return

        skipped = skipped_non_revertable + unresolved
        if skipped:
            self.notify(  # type: ignore[attr-defined]
                f"Skipping {skipped} marked agent(s) not eligible for revert",
                severity="warning",
            )

        intent = build_bulk_revert_intent(targets, target_agents, representative)
        self._submit_bulk_revert_preview(intent, representative)

    def _submit_bulk_revert_preview(
        self,
        intent: BulkRevertIntent,
        representative: Agent,
    ) -> None:
        from ....revert_agent import preview_agents_revert_intent
        from ..proc_actions import TrackedProcResult

        def _callable() -> TrackedProcResult[BulkRevertPreview]:
            preview = preview_agents_revert_intent(intent)
            return TrackedProcResult(
                success=True,
                message=preview.error
                or f"Found {preview.commit_count} commit(s) to revert",
                payload=preview,
            )

        def _on_complete(
            completion: TrackedProcCompletion[BulkRevertPreview],
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

        self._submit_tracked_proc(  # type: ignore[attr-defined]
            "revert_preview",
            representative.cl_name,
            representative.project_file,
            _callable,
            display_name=f"Revert preview: {len(intent.targets)} marked agents",
            dedup_key=_bulk_revert_dedup_key("revert_preview", intent),
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
        from ....revert_agent import (
            build_bulk_revert_execute_intent,
            execute_agents_revert_intent,
        )
        from ..proc_actions import TrackedProcResult

        intent = build_bulk_revert_execute_intent(representative, preview)

        def _callable() -> TrackedProcResult[BulkRevertResult]:
            result = execute_agents_revert_intent(preview, intent)
            return TrackedProcResult(
                success=result.success,
                message=result.message,
                payload=result,
                error=result.error,
            )

        def _on_complete(
            completion: TrackedProcCompletion[BulkRevertResult],
        ) -> None:
            # Refresh on success or when a local revert commit was created even
            # though the post-commit push failed (the worktree state changed).
            payload = completion.payload
            if completion.success or (payload is not None and payload.reverted_shas):
                self._schedule_agents_async_refresh(source="revert_agent")  # type: ignore[attr-defined]

        self._submit_tracked_proc(  # type: ignore[attr-defined]
            "revert_agent",
            representative.cl_name,
            representative.project_file,
            _callable,
            display_name=f"Revert {preview.target_count} marked agents",
            dedup_key=_bulk_revert_dedup_key("revert_agent", intent),
            on_complete=_on_complete,
            reload_on_complete=False,
            notify_on_complete=True,
        )


def _revert_dedup_key(prefix: str, intent: RevertIntent) -> str:
    """Stable dedup key from immutable intent data (not a claimed workspace)."""
    parts = [prefix, intent.agent_name, intent.project_file, intent.cl_name]
    if intent.linked_repo_names:
        parts.append(",".join(sorted(intent.linked_repo_names)))
    if intent.external_repos:
        parts.append(",".join(sorted(repo.label for repo in intent.external_repos)))
    if intent.external_artifact_dirs:
        parts.append(
            ",".join(
                sorted(
                    f"{source_name}={artifacts_dir}"
                    for source_name, artifacts_dir in intent.external_artifact_dirs
                )
            )
        )
    return ":".join(parts)


def _bulk_revert_dedup_key(prefix: str, intent: BulkRevertIntent) -> str:
    """Stable dedup key for a bulk revert from immutable intent data."""
    names = ",".join(sorted(t.agent_name for t in intent.targets))
    parts = [prefix, "bulk", names, intent.project_file, intent.cl_name]
    if intent.linked_repo_names:
        parts.append(",".join(sorted(intent.linked_repo_names)))
    if intent.external_repos:
        parts.append(",".join(sorted(repo.label for repo in intent.external_repos)))
    if intent.external_artifact_dirs:
        parts.append(
            ",".join(
                sorted(
                    f"{source_name}={artifacts_dir}"
                    for source_name, artifacts_dir in intent.external_artifact_dirs
                )
            )
        )
    return ":".join(parts)
