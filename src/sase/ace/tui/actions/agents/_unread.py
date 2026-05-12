"""Unread completed-agent helpers for the ace TUI app."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from ._loading_helpers import DISMISSABLE_STATUSES

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


def is_unread_completed_status(status: str) -> bool:
    """Return True for terminal statuses that can be surfaced as unread."""
    return status in DISMISSABLE_STATUSES


class AgentUnreadMixin:
    """Mixin providing unread completed-agent state and navigation."""

    _agents: list[Agent]
    current_idx: int
    current_attempt_number: int | None
    _current_group_key: tuple[str, ...] | None
    _unread_completed_agent_ids: set[tuple[AgentType, str, str | None]]
    _manual_unread_agent_ids: set[tuple[AgentType, str, str | None]]

    def _has_unread_completed_agent(self) -> bool:
        """Return True when a visible terminal row is still unread."""
        unread_ids: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        if not unread_ids:
            return False
        return any(
            is_unread_completed_status(agent.status) and agent.identity in unread_ids
            for agent in self._agents
        )

    def _mark_all_unread_done_agents_read(self) -> int:
        """Acknowledge all currently loaded unread terminal agent rows."""
        unread_ids = getattr(self, "_unread_completed_agent_ids", None)
        if not unread_ids:
            return 0

        target_agents = [
            agent
            for agent in self._agents
            if agent.identity in unread_ids and is_unread_completed_status(agent.status)
        ]
        if not target_agents:
            return 0

        target_identities = {agent.identity for agent in target_agents}
        unread_ids.difference_update(target_identities)
        self._manual_unread_ids().difference_update(target_identities)

        agent_keys = [
            {"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix}
            for agent in target_agents
        ]

        from sase.notifications import (
            dismiss_agent_completion_notifications_matching_agents,
        )

        dismissed_count = dismiss_agent_completion_notifications_matching_agents(
            agent_keys
        )
        if dismissed_count:
            refresh_count = getattr(self, "_refresh_notification_count", None)
            if callable(refresh_count):
                refresh_count()

        self._refresh_agents_display(  # type: ignore[attr-defined]
            list_changed=True,
        )
        return len(target_agents)

    def _jump_to_next_unread_done_agent(self) -> bool:
        """Move focus to the next visible unread completed agent and acknowledge it."""
        if not self._agents:
            return False

        visible_panel_indices = self._visible_agent_panel_indices()  # type: ignore[attr-defined]
        if not visible_panel_indices:
            return False

        unread_ids: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        if not unread_ids:
            return False

        candidates: list[tuple[int, int | None, datetime | None]] = []
        for idx, agent in enumerate(self._agents):
            if idx not in visible_panel_indices:
                continue
            if (
                is_unread_completed_status(agent.status)
                and agent.identity in unread_ids
            ):
                candidates.append(
                    (
                        idx,
                        visible_panel_indices[idx],
                        agent.stop_time or agent.start_time,
                    )
                )

        if not candidates:
            return False

        candidates.sort(
            key=lambda candidate: candidate[2] or datetime.min, reverse=True
        )

        target_pos = 0
        if getattr(self, "_current_group_key", None) is None:
            for candidate_pos, (idx, _panel_idx, _completion_time) in enumerate(
                candidates
            ):
                if idx == self.current_idx:
                    target_pos = (candidate_pos + 1) % len(candidates)
                    break

        target_idx, target_panel_idx, _completion_time = candidates[target_pos]
        old_idx = self.current_idx
        old_panel_idx = getattr(
            getattr(self, "_panel_group", None), "focused_idx", None
        )
        old_group_key = self._current_group_key
        target_agent = self._agents[target_idx]
        panel_changed = False
        panel_group = getattr(self, "_panel_group", None)
        if (
            panel_group is not None
            and target_panel_idx is not None
            and 0 <= target_panel_idx < len(panel_group.panel_keys)
            and target_panel_idx != panel_group.focused_idx
        ):
            panel_group.focused_idx = target_panel_idx
            panel_changed = old_panel_idx != target_panel_idx
        self._current_group_key = None
        self.current_idx = target_idx
        if hasattr(self, "current_attempt_number"):
            self.current_attempt_number = None  # type: ignore[attr-defined]

        needs_full_refresh = panel_changed or (
            old_idx == target_idx and old_group_key is not None
        )
        if needs_full_refresh:
            self._clear_agent_unread_and_dismiss_notification(target_agent)
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=True, defer_detail=True
            )
        else:
            self._acknowledge_agent_unread(target_agent)
        return True

    def _manual_unread_ids(self) -> set[tuple[AgentType, str, str | None]]:
        """Return the session-local manual unread guard set."""
        manual_ids = getattr(self, "_manual_unread_agent_ids", None)
        if manual_ids is None:
            manual_ids = set()
            self._manual_unread_agent_ids = manual_ids
        return manual_ids

    def _arm_manual_unread_after_departure(self, agent: Agent | None) -> None:
        """Let a manually unread row clear normally the next time it is selected."""
        if agent is None:
            return
        self._manual_unread_ids().discard(agent.identity)

    def _clear_agent_unread_and_dismiss_notification(self, agent: Agent) -> bool:
        """Clear unread state for *agent* and dismiss its matching notification.

        Returns True only when the agent moved from unread to read. When the
        agent is in a terminal status, any active completion notification
        targeting the same ``(cl_name, raw_suffix)`` is dismissed and the
        notification indicator is refreshed so the one-to-one row/notification
        contract holds.
        """
        if agent.identity in self._manual_unread_ids():
            return False

        unread_ids = getattr(self, "_unread_completed_agent_ids", None)
        if unread_ids is None or agent.identity not in unread_ids:
            return False

        unread_ids.discard(agent.identity)

        if not is_unread_completed_status(agent.status):
            return True

        from sase.notifications import dismiss_notifications_matching_agents

        dismissed_count = dismiss_notifications_matching_agents(
            [{"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix}]
        )
        if dismissed_count:
            refresh_count = getattr(self, "_refresh_notification_count", None)
            if callable(refresh_count):
                refresh_count()
        return True

    def _acknowledge_agent_unread(self, agent: Agent) -> bool:
        """Clear unread for *agent* unless it is manually guarded.

        Returns True when the visible row was patched or refreshed.
        """
        if not self._clear_agent_unread_and_dismiss_notification(agent):
            return False

        if not self._try_patch_agent_row(agent):  # type: ignore[attr-defined]
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=True, defer_detail=True
            )
        return True

    def _toggle_agent_unread(self) -> None:
        """Toggle the selected Agents-tab row's manual unread marker."""
        if getattr(self, "_current_group_key", None) is not None:
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return

        identity = agent.identity
        unread_ids = getattr(self, "_unread_completed_agent_ids", None)
        if unread_ids is None:
            unread_ids = set()
            self._unread_completed_agent_ids = unread_ids  # type: ignore[attr-defined]
        manual_ids = self._manual_unread_ids()

        if identity in manual_ids:
            manual_ids.discard(identity)
            self._clear_agent_unread_and_dismiss_notification(agent)
        else:
            manual_ids.add(identity)
            unread_ids.add(identity)

        if not self._try_patch_agent_row(agent):  # type: ignore[attr-defined]
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=True, defer_detail=True
            )
