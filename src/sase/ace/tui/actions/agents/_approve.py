"""Agent auto-approve action for the ace TUI app."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sase.agent.status_buckets import ACTIVE_PLAN_HANDOFF_STATUSES
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...modals import AutoApproveChoice

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]

# Agent statuses for which auto-approval can be configured.
_APPROVE_ELIGIBLE = frozenset(
    {
        "STARTING",
        "RUNNING",
        "PLAN",
        *ACTIVE_PLAN_HANDOFF_STATUSES,
        "WAITING",
        "QUESTION",
    }
)


def _persist_plan_auto_approval(
    meta_path: Path,
    approve: bool,
    auto_approve_plan_action: str | None,
) -> None:
    """Read ``agent_meta.json``, update auto-approval fields, and write it back.

    Runs on a worker thread; raises on filesystem errors so the scheduler
    can surface them to the user as a toast.
    """
    meta: dict[str, object] = {}
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        # Missing/corrupt file is recoverable — we'll write a fresh one.
        meta = {}
    if approve:
        meta["approve"] = True
    else:
        meta.pop("approve", None)
    if auto_approve_plan_action:
        meta["auto_approve_plan_action"] = auto_approve_plan_action
    else:
        meta.pop("auto_approve_plan_action", None)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    update_agent_artifact_index_for_marker_mutation(meta_path.parent)


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

        The disk write is dispatched to a worker via
        :func:`sase.ace.tui.util.io_async.schedule_persist` so the UI thread
        never blocks on I/O. The in-memory ``agent.approve`` /
        ``auto_approve_plan_action`` fields are patched optimistically and
        reverted if the persistence worker fails.
        """
        from ...util.io_async import schedule_persist

        artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
        if not artifacts_dir:
            self.notify("No artifacts directory for agent", severity="warning")  # type: ignore[attr-defined]
            return

        prior_approve = agent.approve
        prior_auto_action = agent.auto_approve_plan_action
        new_approve, new_auto_action, toast = _auto_approval_state_for_choice(choice)
        agent.approve = new_approve
        agent.auto_approve_plan_action = new_auto_action
        # Auto-approve flips a couple of in-memory fields — try the selective
        # patch first; fall back to the full rebuild if the row can't be
        # patched in place (cross-group risk, alignment overflow, etc.).
        if not self._try_patch_agent_row(agent):  # type: ignore[attr-defined]
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

        meta_path = Path(artifacts_dir) / "agent_meta.json"

        def _rollback(exc: BaseException) -> None:
            del exc
            agent.approve = prior_approve
            agent.auto_approve_plan_action = prior_auto_action
            if not self._try_patch_agent_row(agent):  # type: ignore[attr-defined]
                self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

        schedule_persist(
            self,  # type: ignore[arg-type]
            _persist_plan_auto_approval,
            meta_path,
            # The persisted ``approve`` key is only written for a plain plan
            # auto-approve; tale/epic carry their state in the action instead.
            new_approve and new_auto_action is None,
            new_auto_action,
            error_label="Auto-approve persist",
            on_error=_rollback,
        )

        self.notify(toast)  # type: ignore[attr-defined]
