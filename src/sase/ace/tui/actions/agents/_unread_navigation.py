"""Time-ordered unread and stopped-agent navigation helpers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from sase.agent.status_buckets import is_pending_plan_review_status

from ...models.agent_status import (
    is_stopped_agent_status,
    is_unread_completed_status,
)
from ._unread_jump_candidates import (
    AgentUnreadJumpCandidatesMixin,
    TimedAgentJumpCandidate,
)
from ._unread_state import AgentUnreadStateMixin
from ._panel_fold_intent import panel_is_collapsed

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


def _stopped_agent_jump_time(agent: Agent) -> datetime | None:
    """Return the best timestamp for ordering stopped-agent jumps."""
    if is_pending_plan_review_status(agent.status) and agent.plan_times:
        return max(agent.plan_times)
    if agent.status == "QUESTION" and agent.questions_times:
        return max(agent.questions_times)
    return agent.stop_time or agent.start_time


class AgentUnreadNavigationMixin(
    AgentUnreadStateMixin,
    AgentUnreadJumpCandidatesMixin,
):
    """Mixin providing unread and stopped-agent navigation."""

    _agents: list[Agent]
    current_idx: int
    current_attempt_number: int | None
    _current_group_key: tuple[str, ...] | None
    _expanded_panel_focus: bool
    _unread_completed_agent_ids: set[tuple[AgentType, str, str | None]]

    def _has_unread_completed_agent(self) -> bool:
        """Return True when an unread terminal row is currently jumpable."""
        unread_ids: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        if not unread_ids:
            return False
        return bool(self._unread_timed_jump_candidates())

    def _has_stopped_agent(self) -> bool:
        """Return True when a stopped agent row is currently loaded."""
        return any(is_stopped_agent_status(agent.status) for agent in self._agents)

    def _jump_to_next_unread_done_agent(self) -> bool:
        """Reveal and select the next unread completed agent, then acknowledge it."""
        unread_ids: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        if not unread_ids:
            return False

        def acknowledge_target(
            agent: Agent,
            needs_full_refresh: bool,
            panel_expanded: bool,
        ) -> None:
            if panel_expanded:
                self._clear_agent_unread_and_dismiss_notification(agent)
                self._refresh_agents_display(  # type: ignore[attr-defined]
                    list_changed=True, defer_detail=True
                )
            elif needs_full_refresh:
                before_unread = set(getattr(self, "_unread_completed_agent_ids", set()))
                changed = self._clear_agent_unread_and_dismiss_notification(agent)
                if changed and not self._repaint_changed_unread_rows(before_unread):
                    return
                self._refresh_agents_display(  # type: ignore[attr-defined]
                    list_changed=False, defer_detail=True
                )
            else:
                self._acknowledge_agent_unread(agent)

        def predicate(agent: Agent) -> bool:
            return agent.identity in unread_ids and is_unread_completed_status(
                agent.status
            )

        return self._jump_to_next_matching_agent_by_time(
            predicate=predicate,
            after_select=acknowledge_target,
            include_collapsed_clan_members=True,
            candidates=self._unread_timed_jump_candidates(),
        )

    def _jump_to_next_stopped_agent(self) -> bool:
        """Move focus to the next visible stopped agent without acknowledging it."""
        return self._jump_to_next_matching_agent_by_time(
            predicate=lambda agent: is_stopped_agent_status(agent.status),
            after_select=None,
            time_for_agent=_stopped_agent_jump_time,
        )

    def _jump_to_next_matching_agent_by_time(
        self,
        *,
        predicate: Callable[[Agent], bool],
        after_select: Callable[[Agent, bool, bool], None] | None,
        time_for_agent: Callable[[Agent], datetime | None] | None = None,
        include_collapsed_clan_members: bool = False,
        candidates: list[TimedAgentJumpCandidate] | None = None,
    ) -> bool:
        """Move focus to the next jumpable agent matching *predicate* by recency."""
        if candidates is None:
            candidates = self._timed_agent_jump_candidates(
                predicate=predicate,
                time_for_agent=time_for_agent,
                include_collapsed_clan_members=include_collapsed_clan_members,
            )
        if not candidates:
            return False

        target_pos = 0
        panel_group = getattr(self, "_panel_group", None)
        visible_panel_indices = self._visible_agent_panel_indices(  # type: ignore[attr-defined]
            include_collapsed_panels=True
        )
        focused_panel_is_collapsed = panel_group is not None and panel_is_collapsed(
            self, panel_group.focused_key
        )
        resolve_focused_panel = getattr(self, "_resolve_focused_panel", None)
        focused_panel = (
            resolve_focused_panel() if callable(resolve_focused_panel) else None
        )
        origin_is_panel = focused_panel is not None or focused_panel_is_collapsed
        current_panel_idx = visible_panel_indices.get(self.current_idx)
        current_is_visible_agent = (
            getattr(self, "_current_group_key", None) is None
            and self.current_idx in visible_panel_indices
            and not origin_is_panel
            and (
                panel_group is None
                or current_panel_idx == getattr(panel_group, "focused_idx", None)
            )
        )
        if current_is_visible_agent:
            current_identity = self._agents[self.current_idx].identity
            for candidate_pos, candidate in enumerate(candidates):
                if candidate.identity == current_identity:
                    target_pos = (candidate_pos + 1) % len(candidates)
                    break

        target = candidates[target_pos]
        if target.clan_fold_key is not None:
            return self._reveal_and_select_timed_jump_candidate(
                target,
                predicate=predicate,
                after_select=after_select,
            )

        target_idx = target.visible_idx
        if target_idx is None or not (0 <= target_idx < len(self._agents)):
            return False
        target_panel_key = target.panel_key
        old_idx = self.current_idx
        old_panel_key = panel_group.focused_key if panel_group is not None else None
        old_group_key = self._current_group_key
        panel_was_collapsed = panel_group is not None and panel_is_collapsed(
            self, target_panel_key
        )
        focus_will_change = (
            old_idx != target_idx
            or old_group_key is not None
            or target_panel_key != old_panel_key
            or panel_was_collapsed
            or origin_is_panel
        )
        save_jump_anchor = getattr(self, "_save_agents_jump_anchor", None)
        if focus_will_change and callable(save_jump_anchor):
            save_jump_anchor()

        panel_expanded = False
        if panel_was_collapsed:
            expand_panel = getattr(self, "_expand_agent_panel", None)
            if callable(expand_panel):
                panel_expanded = bool(expand_panel(target_panel_key))

        self._expanded_panel_focus = False
        target_agent = self._agents[target_idx]
        panel_changed = target_panel_key != old_panel_key
        if panel_group is not None:
            try:
                target_panel_idx = panel_group.panel_keys.index(target_panel_key)
            except ValueError:
                return False
            if target_panel_idx != panel_group.focused_idx:
                panel_group.focused_idx = target_panel_idx
        self._current_group_key = None
        self.current_idx = target_idx
        if hasattr(self, "current_attempt_number"):
            self.current_attempt_number = None  # type: ignore[attr-defined]

        needs_full_refresh = (
            origin_is_panel
            or panel_changed
            or (old_idx == target_idx and old_group_key is not None)
        )
        if after_select is not None:
            after_select(target_agent, needs_full_refresh, panel_expanded)
        elif panel_expanded:
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=True, defer_detail=True
            )
        elif needs_full_refresh:
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=False, defer_detail=True
            )
        return True

    def _reveal_and_select_timed_jump_candidate(
        self,
        target: TimedAgentJumpCandidate,
        *,
        predicate: Callable[[Agent], bool],
        after_select: Callable[[Agent, bool, bool], None] | None,
    ) -> bool:
        """Expand one target clan, refilter, resolve by identity, and select."""
        save_jump_anchor = getattr(self, "_save_agents_jump_anchor", None)
        if callable(save_jump_anchor):
            save_jump_anchor()

        fold_manager = getattr(self, "_fold_manager", None)
        if fold_manager is None or target.clan_fold_key is None:
            return False
        if not fold_manager.expand(target.clan_fold_key):
            return False

        # Expand an already-known collapsed tribe panel before the structural
        # refilter so both fold changes land in one rebuilt projection.
        expand_panel = getattr(self, "_expand_agent_panel", None)
        if callable(expand_panel):
            expand_panel(target.panel_key)

        invalidate = getattr(self, "_invalidate_agent_panel_cache", None)
        if callable(invalidate):
            invalidate()
        refilter = getattr(self, "_refilter_agents", None)
        if not callable(refilter):
            return False
        self._expanded_panel_focus = False
        try:
            refilter(refresh_content_index=False)
        except TypeError:
            refilter()

        target_idx = next(
            (
                idx
                for idx, agent in enumerate(self._agents)
                if agent.identity == target.identity
            ),
            None,
        )
        if target_idx is None:
            return False
        target_agent = self._agents[target_idx]
        unread_ids: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        if target_agent.identity not in unread_ids or not predicate(target_agent):
            return False

        visible = self._visible_agent_panel_indices(  # type: ignore[attr-defined]
            include_collapsed_panels=True
        )
        if target_idx not in visible:
            return False

        panel_group = getattr(self, "_panel_group", None)
        target_panel_idx = visible[target_idx]
        target_panel_key = None
        if panel_group is not None:
            if target_panel_idx is None or not (
                0 <= target_panel_idx < len(panel_group.panel_keys)
            ):
                return False
            target_panel_key = panel_group.panel_keys[target_panel_idx]

        panel_expanded_after_refilter = False
        if (
            panel_group is not None
            and panel_is_collapsed(self, target_panel_key)
            and callable(expand_panel)
        ):
            panel_expanded_after_refilter = bool(expand_panel(target_panel_key))

        if panel_group is not None and target_panel_idx != panel_group.focused_idx:
            panel_group.focused_idx = target_panel_idx
        self._current_group_key = None
        self.current_idx = target_idx
        if hasattr(self, "current_attempt_number"):
            self.current_attempt_number = None  # type: ignore[attr-defined]

        if after_select is not None:
            after_select(target_agent, True, panel_expanded_after_refilter)
        elif panel_expanded_after_refilter:
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=True,
                defer_detail=True,
            )
        else:
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=False,
                defer_detail=True,
            )
        return True
