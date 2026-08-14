"""Agent marking actions for the ace TUI app."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
)

from ._cleanup_procs import CleanupProcOutcome
from ._dismiss_cleanup import AgentIdentity
from ._marking_kill import AgentMarkedKillMixin
from ._recent_dismissal_groups import cache_recent_dismissed_agent_group
from ._saved_group_records import (
    build_saved_agent_group,
    normalize_saved_group_name,
    plural_agent,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from sase.core.agent_group_archive_wire import SavedAgentGroupWire

log = logging.getLogger(__name__)


def _persist_marked_agent_group_save(
    agents: list[Agent],
    dismissed_snapshot: set[AgentIdentity],
    added: set[AgentIdentity],
    group: SavedAgentGroupWire,
    group_name: str | None = None,
) -> None:
    """Persist non-killing marked-agent dismissal side effects."""
    del group_name

    from ....dismissed_agents import (
        record_recent_dismissed_agent_group,
        save_dismissed_agent_group,
        save_dismissed_agents,
        save_dismissed_bundle,
    )

    for agent in agents:
        if not agent._from_patch:
            save_dismissed_bundle(agent)

    save_dismissed_agent_group(group)
    record_recent_dismissed_agent_group(group)

    from sase.notifications import (
        dismiss_agent_completion_notifications_matching_agents,
    )

    dismiss_agent_completion_notifications_matching_agents(
        [{"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix} for agent in agents]
    )

    if save_dismissed_agents(dismissed_snapshot):
        try:
            sync_dismissed_agent_artifact_index(dismissed_snapshot, added=added)
        except Exception:
            pass


class AgentMarkingMixin(AgentMarkedKillMixin):
    """Mixin providing agent marking actions for the Agents tab.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _recent_dismissed_agent_groups: list[SavedAgentGroupWire]
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
    _dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]]

    def _marked_agent_group_candidates(self) -> list[Agent]:
        """Return marked agents plus workflow children cascaded from parents."""
        if not self._marked_agents:
            return []

        marked = set(self._marked_agents)
        parent_keys = {
            (agent.raw_suffix, agent.workflow)
            for agent in self._agents_with_children
            if agent.identity in marked
            and not agent.is_workflow_child
            and agent.raw_suffix is not None
        }
        candidates: list[Agent] = []
        seen: set[AgentIdentity] = set()
        for agent in self._agents_with_children:
            include = agent.identity in marked
            if not include and agent.is_workflow_child:
                include = (agent.parent_timestamp, agent.parent_workflow) in parent_keys
            if not include or agent.identity in seen:
                continue
            candidates.append(agent)
            seen.add(agent.identity)
        return candidates

    def _prompt_and_save_marked_agent_group(self) -> None:
        """Prompt for an optional group name before saving marked agents."""
        if not self._marked_agents:
            self.notify("No agents marked", severity="warning")  # type: ignore[attr-defined]
            return

        agents = self._marked_agent_group_candidates()
        if not agents:
            self._reset_marked_agents()
            self.notify("No marked agents remain", severity="warning")  # type: ignore[attr-defined]
            return

        from ...modals import SaveAgentGroupModal, SaveAgentGroupResult

        def on_dismiss(result: SaveAgentGroupResult | None) -> None:
            if result is None:
                return
            self._save_marked_agent_group(group_name=result.name)

        self.push_screen(  # type: ignore[attr-defined]
            SaveAgentGroupModal(candidate_count=len(agents)),
            on_dismiss,
        )

    def _save_marked_agent_group(self, *, group_name: str | None = None) -> None:
        """Save marked agents as a revivable group and hide them without killing."""
        if not self._marked_agents:
            self.notify("No agents marked", severity="warning")  # type: ignore[attr-defined]
            return

        agents = self._marked_agent_group_candidates()
        if not agents:
            self._reset_marked_agents()
            self.notify("No marked agents remain", severity="warning")  # type: ignore[attr-defined]
            return

        identities = {agent.identity for agent in agents}
        added = identities - self._dismissed_agents
        group = build_saved_agent_group(
            agents, group_name=group_name, resolve_bundle_paths=False
        )
        cache_recent_dismissed_agent_group(self, group)
        for identity in identities:
            self._agent_status_overrides.pop(identity, None)
            self._agent_pre_question_status.pop(identity, None)

        self._dismissed_agents.update(identities)
        self._reset_marked_agents()
        self._apply_dismissal_in_memory(agents)  # type: ignore[attr-defined]
        clear_completion_notifications = getattr(
            self,
            "_dismiss_agent_completion_notifications_for_dismissed_agents",
            None,
        )
        if callable(clear_completion_notifications):
            clear_completion_notifications(agents)

        count = len(agents)
        message = f"Saved and dismissed {count} {plural_agent(count)}"
        notify_after_refresh = getattr(self, "_notify_after_refresh", None)
        if callable(notify_after_refresh):
            notify_after_refresh(message)
        else:
            self.notify(message)  # type: ignore[attr-defined]

        from ....dismissed_agents import snapshot_dismissed_agents

        self._submit_marked_group_save_persistence_task(
            list(agents),
            snapshot_dismissed_agents(self._dismissed_agents),
            added,
            group,
            normalize_saved_group_name(group_name),
        )

    def _submit_marked_group_save_persistence_task(
        self,
        agents: list[Agent],
        dismissed_snapshot: set[AgentIdentity],
        added: set[AgentIdentity],
        group: SavedAgentGroupWire,
        group_name: str | None = None,
    ) -> None:
        """Submit marked-group save persistence as a tracked background task."""
        identities = {agent.identity for agent in agents}
        if identities & self._dismiss_persistence_inflight:
            return
        self._dismiss_persistence_inflight.update(identities)

        count = len(agents)

        def _worker() -> CleanupProcOutcome:
            started = time.perf_counter()
            try:
                _persist_marked_agent_group_save(
                    agents,
                    dismissed_snapshot,
                    added,
                    group,
                    group_name,
                )
            except Exception as exc:
                return CleanupProcOutcome(
                    message=(
                        f"Saved {count} {plural_agent(count)} in memory, but group "
                        f"archive failed: {exc}. Refresh recommended."
                    ),
                    severity="error",
                    notify=True,
                    schedule_agents_refresh_source="mark_error_recovery",
                )
            finally:
                self._dismiss_persistence_inflight.difference_update(identities)
                log.debug(
                    "marked agent group save persistence: count=%d elapsed=%.3fs",
                    count,
                    time.perf_counter() - started,
                )
            return CleanupProcOutcome(
                message=f"Saved {count} {plural_agent(count)}",
                refresh_notifications=True,
            )

        if not self._submit_cleanup_proc(  # type: ignore[attr-defined]
            proc_type="save",
            display_name=f"save {count} {plural_agent(count)}",
            cl_name="",
            project_file="",
            proc_callable=_worker,
        ):
            self._dismiss_persistence_inflight.difference_update(identities)
