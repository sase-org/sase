"""Agent dismissal methods for the ace TUI app."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from sase.core.agent_cleanup_wire import AgentCleanupPlanWire
    from sase.core.agent_group_archive_wire import SavedAgentGroupWire

# Import Patch unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures).
from ....patch import Patch

from ._cleanup_procs import CleanupProcMixin
from ._dismiss_cleanup import (
    AgentIdentity,
    agent_identity_from_wire,
    agent_wire_identity as _agent_wire_identity,
    dismissed_identities_from_plan,
    plan_dismissal_side_effects,
    wire_identity_key as _wire_identity_key,
)
from ._dismiss_memory import AgentDismissMemoryMixin
from ._dismiss_persistence import (
    agents_related_to_dismissal,
)
from ._dismiss_persistence import (
    persist_bulk_dismiss_side_effects,
    persist_cleanup_side_effect_intents,
    persist_dismiss_side_effects,
)
from ._recent_dismissal_groups import (
    agents_for_recent_group,
    build_recent_dismissed_agent_group,
    cache_recent_dismissed_agent_group,
)
from ._killing_utils import (
    delete_agent_artifacts,
    dismiss_notifications_for_agents,
    find_workflow_workspace_from_running_field,
)
from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
)

_agent_identity_from_wire = agent_identity_from_wire
_plan_dismissal_side_effects = plan_dismissal_side_effects
_agents_related_to_dismissal = agents_related_to_dismissal


class AgentDismissingMixin(CleanupProcMixin, AgentDismissMemoryMixin):
    """Mixin providing agent dismissal methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    # Patch state
    patches: list[Patch]
    current_idx: int
    current_tab: str

    # Agent state
    _agents: list[Agent]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]
    _recent_dismissed_agent_groups: list[SavedAgentGroupWire]
    _agents_with_children: list[Agent]
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
    _dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]]

    def _notify_after_refresh(
        self, message: str, *, severity: str = "information"
    ) -> None:
        """Emit a toast after the next refresh tick so modal-pop teardown
        cannot swallow it. Falls back to immediate notify for hosts (tests)
        that don't implement ``call_after_refresh``.
        """
        call_after_refresh = getattr(self, "call_after_refresh", None)
        if call_after_refresh is None:
            self.notify(message, severity=severity)  # type: ignore[attr-defined]
            return
        call_after_refresh(lambda: self.notify(message, severity=severity))  # type: ignore[attr-defined]

    def _dismiss_all_done_agents(self) -> None:
        """Dismiss all done/failed agents after user confirmation."""
        self._dismiss_done_agents_from(
            self._agents_in_focused_panel(),  # type: ignore[attr-defined]
            empty_message="No agents to dismiss",
        )

    def _dismiss_all_done_agents_global(self) -> None:
        """Dismiss all done/failed agents across all loaded panels."""
        self._dismiss_done_agents_from(
            list(self._agents),
            empty_message="No agents to dismiss",
        )

    def _dismiss_done_agents_from(
        self, agents: list[Agent], *, empty_message: str
    ) -> None:
        """Dismiss all done/failed agents from a candidate list."""
        from ._core import DISMISSABLE_STATUSES

        dismissable = [
            a
            for a in agents
            if a.status in DISMISSABLE_STATUSES and a.raw_suffix is not None
        ]

        if not dismissable:
            self.notify(empty_message, severity="warning")  # type: ignore[attr-defined]
            return

        from ._confirmation_sase_agents import confirmation_sase_agent_summary

        desc_parts = confirmation_sase_agent_summary(
            dismissable,
            self._agents_with_children,
        ).subject_lines("Dismiss")
        agent_description = "\n".join(desc_parts)

        from ...modals import ConfirmDismissAllModal

        def on_dismiss(confirmed: bool | None) -> None:
            if confirmed:
                self._do_dismiss_all(dismissable)

        self.push_screen(ConfirmDismissAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]

    def _do_dismiss_all(self, agents: list[Agent]) -> None:
        """Perform batch dismissal of done/failed agents."""
        if not agents:
            return

        agents_with_children_snapshot = list(self._agents_with_children)

        cleanup_plan = plan_dismissal_side_effects(
            agents,
            agents_with_children_snapshot,
        )
        dismissed_identities = dismissed_identities_from_plan(cleanup_plan)
        recent_group = build_recent_dismissed_agent_group(
            agents_for_recent_group(
                dismissed_identities,
                agents_with_children_snapshot,
            )
        )
        cache_recent_dismissed_agent_group(self, recent_group)

        new_identities = dismissed_identities - self._dismissed_agents
        for identity in dismissed_identities:
            self._agent_status_overrides.pop(identity, None)
            self._agent_pre_question_status.pop(identity, None)
        self._dismissed_agents.update(dismissed_identities)

        count = len(agents)
        s = "s" if count != 1 else ""
        self._notify_after_refresh(f"Dismissed {count} agent{s}")
        # Defer the heavy in-memory refilter so the toast widget can paint
        # before the agents list rebuild blocks the UI tick.
        self.call_later(self._apply_dismissal_in_memory, list(agents))  # type: ignore[attr-defined]
        related_agents = _unique_related_agents_for_dismissal(
            agents,
            agents_with_children_snapshot,
        )
        clear_completion_notifications = getattr(
            self,
            "_dismiss_agent_completion_notifications_for_dismissed_agents",
            None,
        )
        if callable(clear_completion_notifications):
            clear_completion_notifications(related_agents)

        from ....dismissed_agents import snapshot_dismissed_agents

        self._submit_bulk_dismiss_persistence_task(
            list(agents),
            snapshot_dismissed_agents(self._dismissed_agents),
            agents_with_children_snapshot,
            cleanup_plan,
            new_identities,
            recent_group,
        )

    def _submit_bulk_dismiss_persistence_task(
        self,
        agents: list[Agent],
        dismissed_snapshot: set[AgentIdentity],
        agents_with_children_snapshot: list[Agent],
        cleanup_plan: object | None = None,
        added: set[AgentIdentity] | None = None,
        recent_group: SavedAgentGroupWire | None = None,
    ) -> None:
        """Submit a batch dismissal's persistence as a tracked proc."""
        identities = {a.identity for a in agents}
        if identities & self._dismiss_persistence_inflight:
            return
        self._dismiss_persistence_inflight.update(identities)

        count = len(agents)
        s = "s" if count != 1 else ""

        from sase.core.agent_cleanup_wire import agent_cleanup_wire_to_json_dict
        from sase.core.agent_group_archive_wire import (
            saved_agent_group_wire_to_json_dict,
        )

        from ..cleanup_payload import json_identities, serialize_agents

        payload = {
            "action": "dismiss",
            "added_identities": json_identities(added or ()),
            "agents": serialize_agents(agents),
            "agents_with_children": serialize_agents(agents_with_children_snapshot),
            "cleanup_plan": (
                agent_cleanup_wire_to_json_dict(cleanup_plan)
                if cleanup_plan is not None
                else None
            ),
            "dismissed_identities": json_identities(dismissed_snapshot),
            "identity": ",".join(sorted(str(item) for item in identities)),
            "message": f"Dismissed {count} agent{s}",
            "recent_group": (
                saved_agent_group_wire_to_json_dict(recent_group)
                if recent_group is not None
                else None
            ),
            "refresh_notifications": True,
            "transaction": "bulk_dismiss",
        }

        def _release() -> None:
            self._dismiss_persistence_inflight.difference_update(identities)

        if not self._submit_cleanup_proc(
            proc_type="dismiss",
            display_name=f"dismiss {count} agent{s}",
            cl_name="",
            project_file="",
            payload=payload,
            on_settled=_release,
        ):
            _release()

    def _dismiss_done_agent(self, agent: Agent) -> None:
        """Dismiss a DONE or completed workflow agent."""
        if agent.raw_suffix is None:
            self.notify("Cannot dismiss agent: no timestamp", severity="error")  # type: ignore[attr-defined]
            return

        agents_with_children_snapshot = list(self._agents_with_children)
        cleanup_plan = plan_dismissal_side_effects(
            [agent],
            agents_with_children_snapshot,
        )
        self._dismiss_planned_agent(agent, cleanup_plan, agents_with_children_snapshot)

    def _dismiss_planned_agent(
        self,
        agent: Agent,
        cleanup_plan: AgentCleanupPlanWire,
        agents_with_children_snapshot: list[Agent] | None = None,
    ) -> None:
        """Dismiss one agent using an already-computed cleanup plan."""
        from ...models.agent import AgentType

        if agents_with_children_snapshot is None:
            agents_with_children_snapshot = list(self._agents_with_children)
        identities = dismissed_identities_from_plan(cleanup_plan)
        if not identities:
            identities = self._collect_dismissal_identities([agent])
        recent_group = build_recent_dismissed_agent_group(
            agents_for_recent_group(identities, agents_with_children_snapshot)
        )
        cache_recent_dismissed_agent_group(self, recent_group)
        new_identities = identities - self._dismissed_agents
        for identity in identities:
            self._agent_status_overrides.pop(identity, None)
            self._agent_pre_question_status.pop(identity, None)
        self._dismissed_agents.update(identities)
        self._append_dismissed_agent_objects([agent], identities)

        if agent.agent_type == AgentType.WORKFLOW:
            self._notify_after_refresh(f"Dismissed workflow {agent.workflow}")
        else:
            self._notify_after_refresh(f"Dismissed agent for {agent.display_name}")
        self._apply_dismissal_in_memory([agent])
        clear_completion_notifications = getattr(
            self,
            "_dismiss_agent_completion_notifications_for_dismissed_agents",
            None,
        )
        if callable(clear_completion_notifications):
            clear_completion_notifications(
                agents_related_to_dismissal(agent, agents_with_children_snapshot)
            )

        from ....dismissed_agents import snapshot_dismissed_agents

        self._submit_dismiss_persistence_task(
            agent,
            snapshot_dismissed_agents(self._dismissed_agents),
            agents_with_children_snapshot,
            cleanup_plan,
            new_identities,
            recent_group,
        )

    def _submit_dismiss_persistence_task(
        self,
        agent: Agent,
        dismissed_snapshot: set[AgentIdentity],
        agents_with_children_snapshot: list[Agent],
        cleanup_plan: object | None = None,
        added: set[AgentIdentity] | None = None,
        recent_group: SavedAgentGroupWire | None = None,
    ) -> None:
        """Submit single-agent dismiss persistence as a tracked proc."""
        identity = agent.identity
        if identity in self._dismiss_persistence_inflight:
            return
        self._dismiss_persistence_inflight.add(identity)

        from sase.core.agent_cleanup_wire import agent_cleanup_wire_to_json_dict
        from sase.core.agent_group_archive_wire import (
            saved_agent_group_wire_to_json_dict,
        )

        from ..cleanup_payload import json_identities, serialize_agent, serialize_agents

        payload = {
            "action": "dismiss",
            "added_identities": json_identities(added or ()),
            "agent": serialize_agent(agent),
            "agents_with_children": serialize_agents(agents_with_children_snapshot),
            "cleanup_plan": (
                agent_cleanup_wire_to_json_dict(cleanup_plan)
                if cleanup_plan is not None
                else None
            ),
            "dismissed_identities": json_identities(dismissed_snapshot),
            "identity": str(identity),
            "message": f"Dismissed {agent.display_name}",
            "recent_group": (
                saved_agent_group_wire_to_json_dict(recent_group)
                if recent_group is not None
                else None
            ),
            "refresh_notifications": True,
            "transaction": "single_dismiss",
        }

        def _release() -> None:
            self._dismiss_persistence_inflight.discard(identity)

        if not self._submit_cleanup_proc(
            proc_type="dismiss",
            display_name=f"dismiss {agent.display_name}",
            cl_name=agent.cl_name,
            project_file=agent.project_file,
            payload=payload,
            on_settled=_release,
        ):
            _release()


def _persist_single_dismiss_transaction(
    agent: Agent,
    dismissed_snapshot: set[AgentIdentity],
    agents_with_children_snapshot: list[Agent],
    cleanup_plan: object | None = None,
    added: set[AgentIdentity] | None = None,
    recent_group: SavedAgentGroupWire | None = None,
    *,
    register_expected_deletion: Callable[[str | None], None] | None = None,
) -> None:
    """Persist all side effects for one optimistic dismiss operation."""
    from ....dismissed_agents import (
        record_recent_dismissed_agent_group,
        save_dismissed_agents,
    )

    if not persist_cleanup_side_effect_intents(
        cleanup_plan,
        agents_with_children_snapshot,
        register_expected_deletion=register_expected_deletion,
    ):
        if register_expected_deletion is None:
            persist_dismiss_side_effects(agent, agents_with_children_snapshot)
        else:
            persist_dismiss_side_effects(
                agent,
                agents_with_children_snapshot,
                register_expected_deletion=register_expected_deletion,
            )
        dismiss_notifications_for_agents(
            agents_related_to_dismissal(agent, agents_with_children_snapshot)
        )
    if recent_group is not None:
        record_recent_dismissed_agent_group(recent_group)
    if save_dismissed_agents(dismissed_snapshot):
        try:
            sync_dismissed_agent_artifact_index(dismissed_snapshot, added=added)
        except Exception:
            pass


def _unique_related_agents_for_dismissal(
    agents: list[Agent],
    agents_with_children_snapshot: list[Agent],
) -> list[Agent]:
    """Return each agent affected by a batch dismissal once, in display order."""
    related: list[Agent] = []
    seen: set[AgentIdentity] = set()
    for agent in agents:
        for rel in agents_related_to_dismissal(agent, agents_with_children_snapshot):
            if rel.identity in seen:
                continue
            seen.add(rel.identity)
            related.append(rel)
    return related


def _persist_bulk_dismiss_transaction(
    agents: list[Agent],
    dismissed_snapshot: set[AgentIdentity],
    agents_with_children_snapshot: list[Agent],
    cleanup_plan: object | None = None,
    added: set[AgentIdentity] | None = None,
    recent_group: SavedAgentGroupWire | None = None,
    *,
    register_expected_deletion: Callable[[str | None], None] | None = None,
) -> None:
    """Persist all side effects for an optimistic batch dismiss operation."""
    from ....dismissed_agents import (
        record_recent_dismissed_agent_group,
        save_dismissed_agents,
    )

    if not persist_cleanup_side_effect_intents(
        cleanup_plan,
        agents_with_children_snapshot,
        register_expected_deletion=register_expected_deletion,
    ):
        if register_expected_deletion is None:
            persist_bulk_dismiss_side_effects(agents, agents_with_children_snapshot)
        else:
            persist_bulk_dismiss_side_effects(
                agents,
                agents_with_children_snapshot,
                register_expected_deletion=register_expected_deletion,
            )
        related: list[Agent] = []
        seen: set[AgentIdentity] = set()
        for agent in agents:
            for rel in agents_related_to_dismissal(
                agent, agents_with_children_snapshot
            ):
                if rel.identity in seen:
                    continue
                seen.add(rel.identity)
                related.append(rel)
        if related:
            dismiss_notifications_for_agents(related)
    if recent_group is not None:
        record_recent_dismissed_agent_group(recent_group)
    if save_dismissed_agents(dismissed_snapshot):
        try:
            sync_dismissed_agent_artifact_index(dismissed_snapshot, added=added)
        except Exception:
            pass


persist_bulk_dismiss_transaction = _persist_bulk_dismiss_transaction
persist_single_dismiss_transaction = _persist_single_dismiss_transaction
