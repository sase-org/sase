"""Incremental AgentList row removal and row patch helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.core.time import local_now

from ...models.agent_groups import (
    GroupingMode,
    status_bucket_for,
    status_grouping_signature,
)
from ._display_helpers import TabName, panel_widget_id
from ._display_panel_titles import agent_panel_border_title, agent_panel_counts
from ._refresh_trace import (
    AgentRefreshDisplayCost,
    AgentRefreshFallbackReason,
    record_agents_refresh_trace,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_panels import AgentPanelGroup


def _status_row_patch_is_safe(old_agent: Agent, new_agent: Agent) -> bool:
    """Whether a ``BY_STATUS`` row may be patched in place for *new_agent*.

    Compares the currently-rendered row (*old_agent*) against the incoming
    *new_agent* under the status-grouping keys. The patch is safe only when the
    row identity is unchanged (same logical row) and the status bucket,
    name-root / name-prefix subgroup, and launch anchor are identical — i.e.
    the change is badge-only and the cached visual position still holds. Any
    difference means the row may move, so the caller must fall back to a
    rebuild.
    """
    if old_agent.identity != new_agent.identity:
        return False
    return status_grouping_signature(old_agent) == status_grouping_signature(new_agent)


def _clan_row_patch_preserves_order(old_agent: Agent, new_agent: Agent) -> bool:
    """Whether a clan-projected row keeps its within-clan status rank."""
    if not (old_agent.tree_depth > 0 or new_agent.tree_depth > 0):
        return True
    return status_bucket_for(old_agent) == status_bucket_for(new_agent)


class PanelPatchMixin:
    """Fast paths for in-place row removal and single-row refreshes."""

    current_idx: int
    current_attempt_number: int | None
    current_tab: TabName
    _agents: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _current_group_key: tuple[str, ...] | None
    _panel_group: AgentPanelGroup
    _agents_first_load_done: bool

    def _record_display_patch_trace(
        self,
        *,
        display_cost: AgentRefreshDisplayCost,
        fallback_reason: AgentRefreshFallbackReason | None = None,
        count: int | None = None,
    ) -> None:
        """Record a structured row patch/remove result for tests and traces."""
        record_agents_refresh_trace(
            self,
            stage="display_patch",
            source=getattr(self, "_agents_refresh_active_source", "local_mutation"),
            display_cost=display_cost,
            fallback_reason=fallback_reason,
            count=count,
        )

    def _try_remove_agent_rows(
        self,
        removed_identities: set[tuple[AgentType, str, str | None]],
    ) -> bool:
        """Apply optimistic removes in place across panel widgets."""
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        if not removed_identities:
            return True
        if self.current_tab != "agents":
            return False
        if getattr(self, "_agent_search_query", ""):
            self._record_display_patch_trace(
                display_cost="row_remove",
                fallback_reason="active_search",
                count=len(removed_identities),
            )
            return False
        if (
            getattr(self, "_grouping_mode", GroupingMode.STANDARD)
            is not GroupingMode.STANDARD
        ):
            self._record_display_patch_trace(
                display_cost="row_remove",
                fallback_reason="unsupported_grouping",
                count=len(removed_identities),
            )
            return False

        if not hasattr(self, "query_one"):
            return False
        try:
            container = self.query_one("#agent-list-container")  # type: ignore[attr-defined]
        except NoMatches:
            self._record_display_patch_trace(
                display_cost="row_remove",
                fallback_reason="panel_membership_change",
                count=len(removed_identities),
            )
            return False

        panel_widgets = [w for w in container.children if isinstance(w, AgentList)]
        target_widget: AgentList | None = None
        for widget in panel_widgets:
            widget_identities = {a.identity for a in widget._agents}
            overlap = widget_identities & removed_identities
            if not overlap:
                continue
            if overlap != removed_identities:
                self._record_display_patch_trace(
                    display_cost="row_remove",
                    fallback_reason="panel_membership_change",
                    count=len(removed_identities),
                )
                return False
            if target_widget is not None:
                self._record_display_patch_trace(
                    display_cost="row_remove",
                    fallback_reason="panel_membership_change",
                    count=len(removed_identities),
                )
                return False
            target_widget = widget

        if target_widget is None:
            from ._panel_fold_intent import effective_panel_collapses

            collapsed_keys = effective_panel_collapses(
                self, getattr(self._panel_group, "panel_keys", ())
            )
            panel_index_fn = getattr(self, "_agent_panel_index", None)
            if collapsed_keys and callable(panel_index_fn):
                panel_index = panel_index_fn()
                collapsed_identities = {
                    agent.identity
                    for key in collapsed_keys
                    for agent in panel_index.slice_for(key).agents
                }
                if collapsed_identities & removed_identities:
                    self._record_display_patch_trace(
                        display_cost="row_remove",
                        fallback_reason="panel_membership_change",
                        count=len(removed_identities),
                    )
                    return False
            return True

        target_identities = {agent.identity for agent in target_widget._agents}
        if target_widget.has_class("-collapsed-panel") or (
            target_identities and target_identities <= removed_identities
        ):
            self._record_display_patch_trace(
                display_cost="row_remove",
                fallback_reason="panel_membership_change",
                count=len(removed_identities),
            )
            return False

        if not target_widget.try_remove_rows(removed_identities):
            self._record_display_patch_trace(
                display_cost="row_remove",
                fallback_reason="workflow_tree_change",
                count=len(removed_identities),
            )
            return False

        self._record_display_patch_trace(
            display_cost="row_remove",
            count=len(removed_identities),
        )
        return True

    def _patch_agent_runtime_rows(self) -> int:
        """Patch visible Agents-tab rows with active runtime suffixes."""
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        if self.current_tab != "agents":
            return 0
        if not getattr(self, "_agents_first_load_done", False):
            return 0

        try:
            container = self.query_one("#agent-list-container")  # type: ignore[attr-defined]
        except NoMatches:
            return 0

        now = local_now()
        patched = 0
        for widget in container.children:
            if isinstance(widget, AgentList):
                patched += widget.patch_active_runtime_rows(now)
        return patched

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        """Patch a single agent's row in place when no group membership changed."""
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        if self.current_tab != "agents":
            return False

        try:
            agent_idx = self._agents.index(agent)
        except ValueError:
            self._record_display_patch_trace(
                display_cost="row_patch",
                fallback_reason="panel_membership_change",
                count=1,
            )
            return False

        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
        agent_panel_key = panel_index.keys_per_agent[agent_idx]

        target_panel_idx: int | None = None
        for idx, key in enumerate(self._panel_group.panel_keys):
            if key == agent_panel_key:
                target_panel_idx = idx
                break
        if target_panel_idx is None:
            self._record_display_patch_trace(
                display_cost="row_patch",
                fallback_reason="panel_membership_change",
                count=1,
            )
            return False

        wid = panel_widget_id(target_panel_idx)
        try:
            widget = self.query_one(f"#{wid}", AgentList)  # type: ignore[attr-defined]
        except NoMatches:
            self._record_display_patch_trace(
                display_cost="row_patch",
                fallback_reason="panel_membership_change",
                count=1,
            )
            return False

        local_idx = panel_index.local_idx_for(agent_panel_key, agent_idx)
        if local_idx < 0:
            self._record_display_patch_trace(
                display_cost="row_patch",
                fallback_reason="panel_membership_change",
                count=1,
            )
            return False

        if local_idx >= len(widget._agents):
            self._record_display_patch_trace(
                display_cost="row_patch",
                fallback_reason="panel_membership_change",
                count=1,
            )
            return False

        if not _clan_row_patch_preserves_order(
            widget._agents[local_idx],
            agent,
        ):
            # Direct clan-member units are ordered by the visible anchor's
            # status in every grouping mode. A bucket change therefore needs
            # re-projection even in STANDARD/BY_DATE, where status normally
            # has no effect on row position.
            self._record_display_patch_trace(
                display_cost="row_patch",
                fallback_reason="clan_member_order_change",
                count=1,
            )
            return False

        if getattr(
            self, "_grouping_mode", GroupingMode.STANDARD
        ) is GroupingMode.BY_STATUS and not _status_row_patch_is_safe(
            widget._agents[local_idx], agent
        ):
            # Under BY_STATUS a row patch is only safe for a non-structural
            # change (e.g. a deferred live-hint pencil): the row must stay in
            # the same status bucket, name-root/name-prefix subgroup, and launch
            # anchor so its cached visual position is still valid. A bucket,
            # hierarchy, or recency change requires a panel rebuild.
            self._record_display_patch_trace(
                display_cost="row_patch",
                fallback_reason="unsupported_grouping",
                count=1,
            )
            return False

        widget._agents[local_idx] = agent

        is_selected = (
            agent_idx == self.current_idx
            and self.current_attempt_number is None
            and self._current_group_key is None
        )
        ok = widget.patch_agent_row(
            local_idx,
            marked_agents=self._marked_agents,
            unread_agents=getattr(self, "_unread_completed_agent_ids", set()),
            is_selected=is_selected,
            now=None,
        )
        if not ok:
            self._record_display_patch_trace(
                display_cost="row_patch",
                fallback_reason="width_growth",
                count=1,
            )
            return False

        slot = panel_index.slice_for(agent_panel_key)
        unread: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        title_builder = getattr(self, "_agent_panel_title", None)
        title_setter = getattr(self, "_set_agent_panel_title", None)
        if callable(title_builder) and callable(title_setter):
            title_setter(
                widget,
                title_builder(
                    agent_panel_key,
                    slot.agents,
                    merge_tribe_panels=getattr(self, "_agent_panels_grouped", False),
                ),
            )
        else:
            counts = agent_panel_counts(slot.agents, unread)
            widget.border_title = agent_panel_border_title(
                agent_panel_key,
                counts.total,
                merge_tribe_panels=getattr(self, "_agent_panels_grouped", False),
                counts=counts,
            )
        self._update_agents_info_panel()  # type: ignore[attr-defined]
        self._record_display_patch_trace(display_cost="row_patch", count=1)
        return True
