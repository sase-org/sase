"""Agent auto-approve toggle for sase's TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ..proc_actions import TrackedProcCompletion

if TYPE_CHECKING:
    from ...models import Agent

# Type alias for tab names
TabName = Literal["artifacts", "agents", "services"]


def _approve_eligible_statuses() -> frozenset[str]:
    """Return statuses that can receive an auto-approval directive."""
    from sase.agent.status_buckets import AUTO_APPROVE_ELIGIBLE_STATUSES

    return AUTO_APPROVE_ELIGIBLE_STATUSES


def _auto_approve_active(agent: Agent) -> bool:
    """Return whether any auto-approval is active on ``agent``.

    Checks both ``approve`` and ``auto_approve_plan_action``: in-memory
    ``approve`` stays ``True`` for tale/epic agents, but launch-time
    ``%auto:tale`` / ``%auto:epic`` agents may carry the action field, so
    check both to be safe.
    """
    return bool(agent.approve or agent.auto_approve_plan_action)


class AgentApproveMixin:
    """Mixin providing the agent bare-``%auto`` toggle.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]

    def action_toggle_auto_approve(self) -> None:
        """Toggle bare ``%auto`` plan auto-approval for the selected agent.

        If auto-approval is off, enable bare ``%auto`` (approving whatever
        plan tier the agent proposes). If any auto-approval is on (``%auto``,
        ``%auto:plan``, ``%auto:tale``, or ``%auto:epic``, whether from launch
        or from a previous toggle), disable it. No panel is opened.
        """
        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        if agent.status not in _approve_eligible_statuses():
            self.notify("Agent not in an active status", severity="warning")  # type: ignore[attr-defined]
            return

        self._set_auto_approve(agent, enabled=not _auto_approve_active(agent))

    def _set_auto_approve(self, agent: Agent, *, enabled: bool) -> None:
        """Enable or disable bare ``%auto`` for ``agent`` and persist it.

        The disk write is dispatched to the tracked task queue so the UI thread
        never blocks on I/O. The in-memory ``agent.approve`` /
        ``auto_approve_plan_action`` fields are patched optimistically and
        reverted if the persistence worker fails.
        """
        artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
        if not artifacts_dir:
            self.notify("No artifacts directory for agent", severity="warning")  # type: ignore[attr-defined]
            return

        prior_approve = agent.approve
        prior_auto_action = agent.auto_approve_plan_action
        if enabled:
            new_approve: bool = True
            new_auto_action: str | None = None
            toast = "Auto-approve enabled (%auto)"
            meta_set: dict[str, object] = {"approve": True}
            auto_mode: Literal["plan", "tale", "epic"] | None = "plan"
        else:
            new_approve = False
            new_auto_action = None
            toast = "Auto-approve disabled"
            meta_set = {}
            auto_mode = None
        generation = object()
        agent._directive_generation = generation  # type: ignore[attr-defined]
        from ..agent_durable import submit_agent_directive

        def _rollback() -> None:
            if getattr(agent, "_directive_generation", None) is not generation:
                return
            agent.approve = prior_approve
            agent.auto_approve_plan_action = prior_auto_action
            if not self._try_patch_agent_row(agent):  # type: ignore[attr-defined]
                self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

        def _on_complete(
            completion: TrackedProcCompletion[object],
        ) -> None:
            if completion.collision or completion.success:
                return
            _rollback()
            self.notify(  # type: ignore[attr-defined]
                f"Auto-approve persist failed: {completion.message}",
                severity="error",
            )

        submitted = submit_agent_directive(
            self,
            artifacts_dir=artifacts_dir,
            payload={
                "meta_remove": [
                    "approve",
                    "auto_approve_plan_action",
                    "auto_approve_argument",
                ],
                "meta_set": meta_set,
                "prompt": {"kind": "set_auto_mode", "mode": auto_mode},
            },
            cl_name=agent.cl_name or agent.display_name or "agent",
            display_name=f"Persist auto: {agent.display_name}",
            on_complete=_on_complete,
        )
        if not submitted:
            return

        agent.approve = new_approve
        agent.auto_approve_plan_action = new_auto_action
        # Auto-approve flips a couple of in-memory fields — try the selective
        # patch first; fall back to the full rebuild if the row can't be
        # patched in place (cross-group risk, alignment overflow, etc.).
        if not self._try_patch_agent_row(agent):  # type: ignore[attr-defined]
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

        self.notify(toast)  # type: ignore[attr-defined]
