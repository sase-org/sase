"""Agent auto-approve action for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sase.agent.status_buckets import AUTO_APPROVE_ELIGIBLE_STATUSES

from ..proc_actions import TrackedProcCompletion

if TYPE_CHECKING:
    from ...models import Agent
    from ...modals import AutoApproveChoice

# Type alias for tab names
TabName = Literal["artifacts", "agents", "axe"]

# Agent statuses for which auto-approval can be configured.
_APPROVE_ELIGIBLE = AUTO_APPROVE_ELIGIBLE_STATUSES


def _auto_approval_choice_for_agent(agent: Agent) -> AutoApproveChoice:
    """Map an agent's current auto-approval state to a menu choice id.

    Used to mark the agent's current standing in the Auto-Approve menu. Note
    ``agent.approve`` stays ``True`` in memory for tale/epic (it drives the row
    icon) even though the persisted ``approve`` key is omitted, so the
    ``auto_approve_plan_action`` value is checked first.
    """
    if agent.auto_approve_plan_action == "epic":
        return "epic"
    if agent.auto_approve_plan_action == "tale":
        return "tale"
    if agent.approve:
        return "plan"
    return "disable"


def _auto_approval_state_for_choice(
    choice: AutoApproveChoice,
) -> tuple[bool, str | None, str]:
    """Map a menu choice to ``(approve, auto_approve_plan_action, toast)``.

    Mirrors the state<->persistence table: tale/epic keep ``approve`` truthy
    in memory while carrying the action; plan is a plain auto-approve; disable
    clears everything.
    """
    if choice == "tale":
        return True, "tale", "Tale auto-approve enabled"
    if choice == "epic":
        return True, "epic", "Epic auto-approve enabled"
    if choice == "plan":
        return True, None, "Auto-approve enabled"
    return False, None, "Auto-approve disabled"


class AgentApproveMixin:
    """Mixin providing the agent auto-approve action.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]

    def action_open_auto_approve_menu(self) -> None:
        """Open the Auto-Approve menu for the selected agent.

        Replaces the old 3-state ``a`` toggle. Pushes the single-key
        :class:`~sase.ace.tui.modals.AutoApproveModal`; the chosen state is
        applied (and persisted) in the dismiss callback via
        :meth:`_apply_auto_approve_choice`. Cancelling leaves the agent
        unchanged.
        """
        from ...modals import AutoApproveModal

        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        if agent.status not in _APPROVE_ELIGIBLE:
            self.notify("Agent not in an active status", severity="warning")  # type: ignore[attr-defined]
            return

        current = _auto_approval_choice_for_agent(agent)

        def _on_dismiss(choice: AutoApproveChoice | None) -> None:
            if choice is None:
                return
            self._apply_auto_approve_choice(agent, choice)

        self.push_screen(AutoApproveModal(current, agent.display_name), _on_dismiss)  # type: ignore[attr-defined]

    def _apply_auto_approve_choice(
        self, agent: Agent, choice: AutoApproveChoice
    ) -> None:
        """Apply and persist an Auto-Approve menu choice for ``agent``.

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
        new_approve, new_auto_action, toast = _auto_approval_state_for_choice(choice)

        auto_mode: Literal["plan", "tale", "epic"] | None
        if choice == "plan":
            auto_mode = "plan"
        elif choice == "tale":
            auto_mode = "tale"
        elif choice == "epic":
            auto_mode = "epic"
        else:
            auto_mode = None
        meta_set: dict[str, object] = {}
        if choice == "plan":
            meta_set["approve"] = True
        elif choice in {"tale", "epic"}:
            meta_set["auto_approve_plan_action"] = choice
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
