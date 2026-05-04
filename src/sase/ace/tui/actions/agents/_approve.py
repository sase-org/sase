"""Agent auto-approve action for the ace TUI app."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


def persist_plan_auto_approval(
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


def persist_approve_field(meta_path: Path, approve: bool) -> None:
    """Backward-compatible wrapper for the legacy boolean auto-approve field."""
    persist_plan_auto_approval(
        meta_path,
        approve=approve,
        auto_approve_plan_action=None,
    )


def _next_auto_approval_state(agent: Agent) -> tuple[bool, str | None, str]:
    if agent.auto_approve_plan_action == "epic":
        return False, None, "Auto-approve disabled"
    if agent.approve:
        return True, "epic", "Epic auto-approve enabled"
    return True, None, "Auto-approve enabled"


class AgentApproveMixin:
    """Mixin providing the agent auto-approve action.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]

    def action_toggle_approve(self) -> None:
        """Toggle auto-approve for the selected agent.

        The disk write is dispatched to a worker via
        :func:`sase.ace.tui.util.io_async.schedule_persist` so the UI thread
        never blocks on I/O. The in-memory ``agent.approve`` flag is flipped
        optimistically and reverted if the persistence worker fails.
        """
        from ...util.io_async import schedule_persist

        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        _APPROVE_ELIGIBLE = {
            "RUNNING",
            "PLANNING",
            "PLAN APPROVED",
            "WAITING",
            "QUESTION",
        }
        if agent.status not in _APPROVE_ELIGIBLE:
            self.notify("Agent not in an active status", severity="warning")  # type: ignore[attr-defined]
            return

        artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
        if not artifacts_dir:
            self.notify("No artifacts directory for agent", severity="warning")  # type: ignore[attr-defined]
            return

        prior_approve = agent.approve
        prior_auto_action = agent.auto_approve_plan_action
        new_approve, new_auto_action, toast = _next_auto_approval_state(agent)
        agent.approve = new_approve
        agent.auto_approve_plan_action = new_auto_action
        # Approve flips one in-memory boolean — try the selective patch
        # first; fall back to the full rebuild if the row can't be
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
            persist_plan_auto_approval,
            meta_path,
            new_approve and new_auto_action is None,
            new_auto_action,
            error_label="Auto-approve persist",
            on_error=_rollback,
        )

        self.notify(toast)  # type: ignore[attr-defined]
