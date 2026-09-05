"""Current-origin capture and trail mutation for ``$`` link-follow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.core.artifact_entry_target import ArtifactEntryTarget

from ..tab_order import ARTIFACTS_TAB
from ._link_follow_ladder import pane_limit_query
from ._link_follow_types import _LINK_TRAIL_MAX, LinkTrailHop
from .axe_display._loader_items import selected_axe_item_key

if TYPE_CHECKING:
    from .axe_display._loader_state import AxeItemKey


class LinkFollowTrailStateMixin:
    """Capture and retain link-follow origin hops."""

    current_tab: Any
    current_idx: int
    _link_trail: list[LinkTrailHop]
    _link_trail_forward: list[LinkTrailHop]

    def _current_link_trail_origin(self) -> LinkTrailHop:
        tab = str(getattr(self, "current_tab", ""))
        pane_key: str | None = None
        origin: ArtifactEntryTarget | None = None
        query_source: str | None = None
        project_scope: str | None = None
        axe_key: AxeItemKey | None = None
        if tab == ARTIFACTS_TAB:
            pane_key = str(getattr(self, "current_artifacts_pane_key", ""))
            pane = self._artifacts_entry_navigator()  # type: ignore[attr-defined]
            if pane is not None:
                origin = pane.selected_entry_target()
                query_source = pane_limit_query(pane)
            project_scope = getattr(self, "artifacts_project_scope", None)
        elif tab == "agents":
            agent = self._get_selected_agent()  # type: ignore[attr-defined]
            name = getattr(agent, "agent_name", None) if agent is not None else None
            if isinstance(name, str) and name:
                origin = ArtifactEntryTarget("agents", (name,))
        elif tab == "axe":
            axe_key = selected_axe_item_key(
                getattr(self, "_axe_items", []),
                getattr(self, "current_idx", -1),
            )
        return LinkTrailHop(
            tab=tab,
            pane_key=pane_key or None,
            origin=origin,
            query_source=query_source,
            project_scope=project_scope,
            axe_key=axe_key,
        )

    def _record_link_trail(self, hop: LinkTrailHop) -> None:
        trail = getattr(self, "_link_trail", None)
        if not isinstance(trail, list):
            trail = []
            self._link_trail = trail
        trail.append(hop)
        if len(trail) > _LINK_TRAIL_MAX:
            del trail[: len(trail) - _LINK_TRAIL_MAX]
        forward = getattr(self, "_link_trail_forward", None)
        if isinstance(forward, list):
            forward.clear()


__all__ = ["LinkFollowTrailStateMixin"]
