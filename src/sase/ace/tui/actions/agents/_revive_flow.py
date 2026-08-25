"""Modal and saved-group flow for agent revival."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ._revive_group_resolution import (
    ref_label,
    resolve_saved_group_agents,
    utc_wire_timestamp,
)
from ._revive_helpers import merge_dismissed_agents
from ._recent_dismissal_groups import (
    cache_recent_dismissed_agent_group,
    load_recent_group_from_cache,
    mark_recent_group_revived_in_cache,
    merge_recent_dismissed_agent_groups,
    recent_group_page_from_cache,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from sase.core.agent_group_archive_wire import SavedAgentGroupWire


class AgentReviveFlowMixin:
    """Mixin providing the user-facing revive modal flow."""

    current_tab: str
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]
    _recent_dismissed_agent_groups: list[SavedAgentGroupWire]

    def action_start_rewind(self) -> None:
        """Dispatch R key: revive on Agents tab, rewind on Patches tab."""
        if self.current_tab == "agents":
            self._revive_agent()
        else:
            super().action_start_rewind()  # type: ignore[misc]

    def _revive_agent(self) -> None:
        """Show saved groups first, then let users open custom revival search."""
        from ....dismissed_agents import (
            delete_dismissed_agent_group,
            list_dismissed_agent_groups,
            list_recent_dismissed_agent_groups,
            load_dismissed_agent_group,
            load_recent_dismissed_agent_group,
        )
        from sase.core.agent_group_archive_wire import SavedAgentGroupPageWire
        from ...modals import (
            SavedAgentGroupRevivalModal,
            SavedAgentGroupRevivalResult,
        )
        from ._revive_log import log_revive_failure

        try:
            recent_disk_page = list_recent_dismissed_agent_groups(limit=10)
            recent_disk_groups = [
                group
                for summary in recent_disk_page.groups
                if (group := load_recent_dismissed_agent_group(summary.group_id))
                is not None
            ]
            self._recent_dismissed_agent_groups = merge_recent_dismissed_agent_groups(
                [
                    *getattr(self, "_recent_dismissed_agent_groups", ()),
                    *recent_disk_groups,
                ]
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to load recent dismissals: {exc}",
                severity="warning",
            )
            if not hasattr(self, "_recent_dismissed_agent_groups"):
                self._recent_dismissed_agent_groups = []

        recent_page = recent_group_page_from_cache(self)

        try:
            initial_page = list_dismissed_agent_groups(limit=20)
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to load saved agent groups: {exc}",
                severity="warning",
            )
            initial_page = SavedAgentGroupPageWire(groups=(), next_cursor=None)

        has_recent_groups = bool(recent_page.groups)
        has_saved_groups = bool(initial_page.groups)
        has_dismissed_agents = bool(
            self._dismissed_agent_objects or self._dismissed_agents
        )
        if not has_recent_groups and not has_saved_groups and not has_dismissed_agents:
            log_revive_failure(
                stage="no_dismissed_agents", reason="no_dismissed_agents"
            )
            self.notify("No dismissed agents to revive")  # type: ignore[attr-defined]
            return

        def _load_page(cursor: int | None) -> SavedAgentGroupPageWire:
            return list_dismissed_agent_groups(limit=20, cursor=cursor)

        def _delete_group(group_id: str) -> bool:
            return delete_dismissed_agent_group(group_id)

        def _load_recent_group(group_id: str) -> SavedAgentGroupWire | None:
            group = load_recent_group_from_cache(self, group_id)
            if group is not None:
                return group
            group = load_recent_dismissed_agent_group(group_id)
            cache_recent_dismissed_agent_group(self, group)
            return group

        def _on_group_revival_selected(
            result: SavedAgentGroupRevivalResult | None,
        ) -> None:
            if result is None:
                return
            if result.action == "custom_search":
                self._open_custom_revival_search()
                return
            if result.action == "revive_group" and result.group_id:
                if result.location == "recent":
                    self._revive_saved_agent_group(
                        result.group_id,
                        location="recent",
                    )
                else:
                    self._revive_saved_agent_group(result.group_id)

        self.app.push_screen(  # type: ignore[attr-defined]
            SavedAgentGroupRevivalModal(
                initial_page,
                recent_page=recent_page,
                page_loader=_load_page,
                group_loader=load_dismissed_agent_group,
                recent_group_loader=_load_recent_group,
                delete_callback=_delete_group,
            ),
            _on_group_revival_selected,
        )

    def _open_custom_revival_search(self) -> None:
        """Open Artifacts -> Agent with the revivable dismissed-agent query."""
        switch = getattr(self, "_switch_artifacts_subtab", None)
        if not callable(switch):
            self.notify(  # type: ignore[attr-defined]
                "Artifacts Agent pane is not available", severity="warning"
            )
            return
        switch("agents")
        pane = getattr(self, "_agents_pane", lambda: None)()
        apply_seed = getattr(pane, "apply_seed_query", None)
        if callable(apply_seed):
            apply_seed("state:dismissed AND revivable:true")
        else:
            self.notify(  # type: ignore[attr-defined]
                "Opened Artifacts -> Agent; filter for revivable dismissed agents",
                severity="information",
            )

    def _revive_saved_agent_group(
        self,
        group_id: str,
        *,
        location: str = "saved",
    ) -> None:
        """Revive the dismissed agents referenced by a saved group."""
        from ....dismissed_agents import (
            load_dismissed_agent_group,
            load_dismissed_bundles,
            load_recent_dismissed_agent_group,
            mark_dismissed_agent_group_revived,
            mark_recent_dismissed_agent_group_revived,
        )
        from ._revive_log import log_revive_failure

        try:
            if location == "recent":
                group = load_recent_group_from_cache(self, group_id)
                if group is None:
                    group = load_recent_dismissed_agent_group(group_id)
                    cache_recent_dismissed_agent_group(self, group)
            else:
                group = load_dismissed_agent_group(group_id)
        except Exception as exc:
            log_revive_failure(
                stage="saved_group_load",
                error=exc,
                group_id=group_id,
            )
            self.notify(  # type: ignore[attr-defined]
                f"Failed to load saved agent group {group_id}: {exc}",
                severity="error",
            )
            return

        if group is None:
            log_revive_failure(
                stage="saved_group_load",
                reason="group_not_found",
                group_id=group_id,
            )
            self.notify(  # type: ignore[attr-defined]
                f"Saved agent group not found: {group_id}",
                severity="warning",
            )
            return

        try:
            resolved, loaded, missing = resolve_saved_group_agents(
                group,
                bundle_loader=load_dismissed_bundles,
            )
        except Exception as exc:
            log_revive_failure(
                stage="saved_group_bundle_load",
                error=exc,
                group_id=group.group_id,
                group_title=group.title,
            )
            self.notify(  # type: ignore[attr-defined]
                f"Failed to load saved group bundles: {exc}",
                severity="error",
            )
            return

        if loaded:
            self._dismissed_agent_objects = merge_dismissed_agents(
                self._dismissed_agent_objects, loaded
            )

        if missing:
            preview = ", ".join(ref_label(ref) for ref in missing[:3])
            suffix = "" if len(missing) <= 3 else f", +{len(missing) - 3} more"
            self.notify(  # type: ignore[attr-defined]
                f"Skipped {len(missing)} missing saved-group agent"
                f"{'s' if len(missing) != 1 else ''}: {preview}{suffix}",
                severity="warning",
            )

        if not resolved:
            log_revive_failure(
                stage="saved_group_bundle_load",
                reason="no_group_refs_loaded",
                group_id=group.group_id,
                group_title=group.title,
            )
            self.notify(  # type: ignore[attr-defined]
                f"No agents could be loaded for saved group {group.title}",
                severity="warning",
            )
            return

        revive_agents = [agent for agent in resolved if not agent.is_workflow_child]
        if not revive_agents:
            revive_agents = resolved

        revived = self._do_revive_agents(  # type: ignore[attr-defined]
            revive_agents,
            group_id=group.group_id,
            group_title=group.title,
        )
        if revived is False or not getattr(revived, "has_changes", True):
            return

        try:
            revived_at = utc_wire_timestamp(datetime.now(UTC))
            if location == "recent":
                mark_recent_dismissed_agent_group_revived(
                    group.group_id,
                    revived_at=revived_at,
                )
                mark_recent_group_revived_in_cache(
                    self,
                    group.group_id,
                    revived_at=revived_at,
                )
                mark_dismissed_agent_group_revived(
                    group.group_id,
                    revived_at=revived_at,
                )
                return
            mark_dismissed_agent_group_revived(
                group.group_id,
                revived_at=revived_at,
            )
        except Exception as exc:
            log_revive_failure(
                stage="saved_group_mark_revived",
                error=exc,
                group_id=group.group_id,
                group_title=group.title,
            )
            self.notify(  # type: ignore[attr-defined]
                f"Revived agents, but failed to mark group revived: {exc}",
                severity="warning",
            )
