"""Agent marking actions for the ace TUI app."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
)
from sase.core.agent_group_archive_wire import (
    SavedAgentGroupRefWire,
    SavedAgentGroupWire,
)

from ._dismiss_cleanup import AgentIdentity

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

TabName = Literal["changespecs", "agents", "axe"]
log = logging.getLogger(__name__)


def _utc_wire_timestamp(value: datetime) -> str:
    """Return a UTC ISO timestamp using the archive wire's ``Z`` convention."""

    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _agent_start_time_wire(agent: Agent) -> str | None:
    if agent.start_time is None:
        return None
    if agent.start_time.tzinfo is None:
        return agent.start_time.isoformat()
    return _utc_wire_timestamp(agent.start_time)


def _agent_project_name(agent: Agent) -> str | None:
    if not agent.project_file:
        return None
    parent = Path(agent.project_file).parent.name
    if parent:
        return parent
    stem = Path(agent.project_file).stem
    return stem or None


def _plural_agent(count: int) -> str:
    return "agent" if count == 1 else "agents"


def _saved_group_title(agents: list[Agent]) -> str:
    count = len(agents)
    tags = sorted({a.tag for a in agents if a.tag})
    cl_names = sorted(
        {a.cl_name for a in agents if a.cl_name and a.cl_name != "unknown"}
    )
    project_names = sorted(
        {name for a in agents if (name := _agent_project_name(a)) is not None}
    )

    if len(tags) == 1:
        return f"{count} {_plural_agent(count)} from @{tags[0]}"
    if len(cl_names) == 1:
        return f"{count} {_plural_agent(count)} in {cl_names[0]}"
    if len(project_names) == 1:
        return f"{count} {_plural_agent(count)} from {project_names[0]}"
    if len(cl_names) > 1:
        return f"{count} {_plural_agent(count)} across {len(cl_names)} CLs"
    return f"{count} {_plural_agent(count)}"


def _normalize_saved_group_name(group_name: str | None) -> str | None:
    if group_name is None:
        return None
    normalized = group_name.strip()
    return normalized or None


def _bundle_path_for_agent(agent: Agent) -> str | None:
    existing = getattr(agent, "_dismissed_bundle_path", None)
    if existing:
        return existing
    if agent.raw_suffix is None:
        return None
    try:
        from ....dismissed_agents import dismissed_bundle_path_for_agent

        path = dismissed_bundle_path_for_agent(agent)
    except Exception:
        return None
    return None if path is None else str(path)


def _saved_group_ref_for_agent(agent: Agent) -> SavedAgentGroupRefWire:
    return SavedAgentGroupRefWire(
        agent_type=agent.agent_type.value,
        cl_name=agent.cl_name,
        raw_suffix=agent.raw_suffix,
        bundle_path=_bundle_path_for_agent(agent),
        is_workflow_child=agent.is_workflow_child,
        parent_timestamp=agent.parent_timestamp,
        display_name=agent.display_name,
        agent_name=agent.agent_name,
        status=agent.status,
        start_time=_agent_start_time_wire(agent),
        model=agent.model,
        llm_provider=agent.llm_provider,
        tag=agent.tag,
    )


def _build_saved_agent_group(
    agents: list[Agent],
    *,
    group_name: str | None = None,
) -> SavedAgentGroupWire:
    now = datetime.now(UTC)
    created_at = _utc_wire_timestamp(now)
    status_counts = dict(sorted(Counter(a.status for a in agents if a.status).items()))
    project_names = tuple(
        sorted({name for a in agents if (name := _agent_project_name(a)) is not None})
    )
    cl_names = tuple(
        sorted({a.cl_name for a in agents if a.cl_name and a.cl_name != "unknown"})
    )
    top_level_count = sum(1 for agent in agents if not agent.is_workflow_child)
    return SavedAgentGroupWire(
        group_id=f"marked-{now.strftime('%Y%m%dT%H%M%S%fZ')}",
        created_at=created_at,
        source="marked_agents",
        title=_saved_group_title(agents),
        name=_normalize_saved_group_name(group_name),
        agent_count=len(agents),
        top_level_agent_count=top_level_count,
        status_counts=status_counts,
        project_names=project_names,
        cl_names=cl_names,
        agent_refs=tuple(_saved_group_ref_for_agent(agent) for agent in agents),
    )


def _persist_marked_agent_group_save(
    agents: list[Agent],
    dismissed_snapshot: set[AgentIdentity],
    added: set[AgentIdentity],
    group_name: str | None = None,
) -> None:
    """Persist non-killing marked-agent dismissal side effects."""

    from ....dismissed_agents import (
        save_dismissed_agent_group,
        save_dismissed_agents,
        save_dismissed_bundle,
    )

    for agent in agents:
        if not agent._from_changespec:
            save_dismissed_bundle(agent)

    group = _build_saved_agent_group(agents, group_name=group_name)
    save_dismissed_agent_group(group)

    if save_dismissed_agents(dismissed_snapshot):
        try:
            sync_dismissed_agent_artifact_index(dismissed_snapshot, added=added)
        except Exception:
            pass


class AgentMarkingMixin:
    """Mixin providing agent marking actions for the Agents tab.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
    _dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]]
    _current_group_key: tuple[str, ...] | None

    def _toggle_mark_agent(self) -> None:
        """Toggle the mark on the currently-selected agent."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        identity = agent.identity
        if identity in self._marked_agents:
            self._marked_agents.discard(identity)
        else:
            self._marked_agents.add(identity)

        # Auto-advance cursor to the next visible agent row (wraparound).
        prev_idx = self.current_idx
        self._advance_mark_selection(prev_idx)

        # Patch the just-marked row in place; the cursor's new position
        # is reflected by the per-panel highlight update so we avoid
        # rebuilding the whole tree for a one-bit mark change.
        patched = self._try_patch_agent_row(agent)  # type: ignore[attr-defined]
        if patched and prev_idx != self.current_idx:
            # Selection moved off prev_idx and onto current_idx — update
            # the on-screen highlight without a rebuild.
            self._refresh_panel_highlights()  # type: ignore[attr-defined]
            # Also patch the now-selected agent so its name styling
            # reflects the new selection state.
            new_agent = self._agents[self.current_idx]
            self._try_patch_agent_row(new_agent)  # type: ignore[attr-defined]
        if not patched:
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

    def _advance_mark_selection(self, prev_idx: int) -> None:
        """Move mark focus to the next visible agent row.

        Marking targets agents, not collapsed banner rows, so auto-advance
        walks ``_agents_visible_order()`` rather than the full selectable
        stop list. When visible-order helpers are unavailable or the
        current agent is hidden, fall back to the legacy raw-list step.
        """
        if len(self._agents) <= 1:
            return

        try:
            visible = self._agents_visible_order()  # type: ignore[attr-defined]
        except Exception:
            visible = []

        if visible:
            try:
                pos = visible.index(prev_idx)
            except ValueError:
                pass
            else:
                self.current_idx = visible[(pos + 1) % len(visible)]
                self._current_group_key = None
                return

        self.current_idx = (prev_idx + 1) % len(self._agents)
        self._current_group_key = None

    def _clear_agent_marks(self) -> None:
        """Clear every agent mark."""
        if not self._marked_agents:
            self.notify("No marks to clear", severity="warning")  # type: ignore[attr-defined]
            return

        count = len(self._marked_agents)
        self._marked_agents = set()
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        self.notify(f"Cleared {count} mark(s)")  # type: ignore[attr-defined]

    def _prune_stale_marked_agents(self) -> None:
        """Drop marked identities that no longer appear in the agent list."""
        if not self._marked_agents:
            return
        live_identities = {a.identity for a in self._agents}
        live_identities.update(a.identity for a in self._agents_with_children)
        stale = self._marked_agents - live_identities
        if stale:
            self._marked_agents -= stale

    def _bulk_kill_marked_agents(self) -> None:
        """Kill / dismiss every marked agent after a single confirmation."""
        if not self._marked_agents:
            return

        marked_agents: list[Agent] = [
            a for a in self._agents_with_children if a.identity in self._marked_agents
        ]
        if not marked_agents:
            self._marked_agents = set()
            self.notify("No marked agents remain", severity="warning")  # type: ignore[attr-defined]
            return

        self._present_bulk_kill_modal(marked_agents)

    def _present_bulk_kill_modal(
        self, agents: list[Agent], *, header: str | None = None
    ) -> None:
        """Show the kill/dismiss confirmation modal for an arbitrary agent set.

        Partitions *agents* into killable (live PID + non-dismissable
        status) and dismissable buckets, builds the per-agent description,
        and pushes the matching ``ConfirmKillAllModal`` /
        ``ConfirmDismissAllModal``.  On confirm, routes through the same
        ``_do_bulk_kill_agents`` machinery used by the marked-set path.
        """
        from ._core import DISMISSABLE_STATUSES

        killable: list[Agent] = [
            a
            for a in agents
            if a.pid is not None and a.status not in DISMISSABLE_STATUSES
        ]
        dismissable: list[Agent] = [
            a for a in agents if a.status in DISMISSABLE_STATUSES or a.pid is None
        ]

        desc_parts: list[str] = []
        if header:
            desc_parts.append(header)
        if killable:
            k_count = len(killable)
            k_s = "s" if k_count != 1 else ""
            desc_parts.append(f"Kill: {k_count} running agent{k_s}")
            for agent in killable:
                name = agent.display_name
                suffix = f" @{agent.agent_name}" if agent.agent_name else ""
                desc_parts.append(f"  {name}{suffix}")
        if dismissable:
            d_count = len(dismissable)
            d_s = "s" if d_count != 1 else ""
            desc_parts.append(f"Dismiss: {d_count} agent{d_s}")
            for agent in dismissable:
                name = agent.display_name
                suffix = f" @{agent.agent_name}" if agent.agent_name else ""
                desc_parts.append(f"  {name}{suffix}")
        agent_description = "\n".join(desc_parts)

        from ...modals import ConfirmDismissAllModal, ConfirmKillAllModal

        def on_dismiss(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._do_bulk_kill_agents(killable, dismissable)  # type: ignore[attr-defined]

        if killable:
            self.push_screen(ConfirmKillAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]
        else:
            self.push_screen(ConfirmDismissAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]

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
            self._marked_agents = set()
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
            self._marked_agents = set()
            self.notify("No marked agents remain", severity="warning")  # type: ignore[attr-defined]
            return

        identities = {agent.identity for agent in agents}
        added = identities - self._dismissed_agents
        for identity in identities:
            self._agent_status_overrides.pop(identity, None)
            self._agent_pre_question_status.pop(identity, None)

        self._dismissed_agents.update(identities)
        self._marked_agents.clear()
        self._apply_dismissal_in_memory(agents)  # type: ignore[attr-defined]

        count = len(agents)
        message = f"Saved and dismissed {count} {_plural_agent(count)}"
        notify_after_refresh = getattr(self, "_notify_after_refresh", None)
        if callable(notify_after_refresh):
            notify_after_refresh(message)
        else:
            self.notify(message)  # type: ignore[attr-defined]

        self.call_later(  # type: ignore[attr-defined]
            self._run_marked_agent_group_save_persistence_async,
            list(agents),
            set(self._dismissed_agents),
            added,
            _normalize_saved_group_name(group_name),
        )

    async def _run_marked_agent_group_save_persistence_async(
        self,
        agents: list[Agent],
        dismissed_snapshot: set[AgentIdentity],
        added: set[AgentIdentity],
        group_name: str | None = None,
    ) -> None:
        """Persist the saved group and dismissed index in a worker thread."""
        identities = {agent.identity for agent in agents}
        if identities & self._dismiss_persistence_inflight:
            return
        self._dismiss_persistence_inflight.update(identities)

        started = time.perf_counter()
        success = True
        try:
            await asyncio.to_thread(
                _persist_marked_agent_group_save,
                agents,
                dismissed_snapshot,
                added,
                group_name,
            )
        except Exception as exc:
            success = False
            count = len(agents)
            self.notify(  # type: ignore[attr-defined]
                f"Saved {count} {_plural_agent(count)} in memory, but group "
                f"archive failed: {exc}. Refresh recommended.",
                severity="error",
            )
            self._schedule_agents_async_refresh(source="mark_error_recovery")  # type: ignore[attr-defined]
        finally:
            self._dismiss_persistence_inflight.difference_update(identities)
            log.debug(
                "marked agent group save persistence: count=%d elapsed=%.3fs",
                len(agents),
                time.perf_counter() - started,
            )
            if success:
                await self._refresh_notification_count_async()  # type: ignore[attr-defined]
