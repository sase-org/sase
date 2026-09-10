"""Open bounded remote chat/output/diff/artifact content."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from sase.dispatch.content import RemoteContentClient

from ._remote_lifecycle import is_remote_fleet_agent

if TYPE_CHECKING:
    from ...models import Agent


class AgentRemoteContentMixin:
    """Fetch remote content handles on explicit open."""

    def action_view_remote_agent_content(self) -> None:
        """Open bounded remote content for the selected fleet row."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if not is_remote_fleet_agent(agent):
            self.notify("Select a remote fleet agent", severity="warning")  # type: ignore[attr-defined]
            return
        handle, row_revision = _content_handle_for(agent)
        if handle is None or row_revision is None:
            self.notify("Remote content is not available", severity="warning")  # type: ignore[attr-defined]
            return
        origin = str(agent.fleet_origin_alias)
        age = _observation_age(getattr(agent, "fleet_observed_at_unix", None))
        from ...modals.remote_content_modal import RemoteContentModal

        self.push_screen(  # type: ignore[attr-defined]
            RemoteContentModal(
                title=f"{agent.agent_name or 'remote agent'} content",
                origin=origin,
                age=age,
                handle=handle,
                row_revision=row_revision,
                observed_at_unix=getattr(agent, "fleet_observed_at_unix", None),
                client=RemoteContentClient(),
            )
        )


def remote_content_available(agent: Agent | None) -> bool:
    """Return whether *agent* advertises a fetchable remote content handle."""
    if not is_remote_fleet_agent(agent):
        return False
    handle, row_revision = _content_handle_for(agent)  # type: ignore[arg-type]
    return handle is not None and row_revision is not None


def _content_handle_for(
    agent: Agent,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    content = getattr(agent, "fleet_content", None)
    handles = None
    if isinstance(content, Mapping):
        raw_handles = content.get("handles") or content.get("content_handles")
        if isinstance(raw_handles, list) and raw_handles:
            first = raw_handles[0]
            if isinstance(first, Mapping):
                handles = dict(first)
    row_revision = _row_revision_for(agent)
    return handles, row_revision


def _row_revision_for(agent: Agent) -> dict[str, Any] | None:
    row_revision = getattr(agent, "fleet_row_revision", None)
    if isinstance(row_revision, Mapping):
        return dict(row_revision)
    logical_key = getattr(agent, "fleet_logical_key", None)
    revision = getattr(agent, "fleet_revision", None)
    if logical_key is not None and revision is not None:
        return {
            "schema_version": 1,
            "logical_key": logical_key,
            "revision": int(revision),
        }
    return None


def _observation_age(observed_at_unix: float | None) -> str:
    if observed_at_unix is None:
        return "unknown"
    elapsed = max(0.0, time.time() - float(observed_at_unix))
    if elapsed < 60:
        return f"{int(elapsed)}s"
    if elapsed < 3600:
        return f"{int(elapsed // 60)}m"
    return f"{int(elapsed // 3600)}h"


__all__ = ["AgentRemoteContentMixin", "remote_content_available"]
