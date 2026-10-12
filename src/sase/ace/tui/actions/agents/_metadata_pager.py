"""The `V` metadata-pager action for the Agents tab."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ...util.trace import tui_trace

if TYPE_CHECKING:
    from sase.pager.document import PagerDocument
    from sase.pager.link_context import LinkResolutionContext

    from ..hints._link_context_capture import CapturedLinkContext
    from ...models.agent import Agent


def _capture_agent_link_context(agent: Agent) -> CapturedLinkContext:
    from ..hints._link_context_capture import CapturedLinkContext

    workspace_dir = getattr(agent, "workspace_dir", None)
    return CapturedLinkContext(
        source="agent",
        workspace_num=getattr(agent, "effective_workspace_num", None),
        project_file=getattr(agent, "project_file", None),
        workspace_dir=(None if workspace_dir is None else str(workspace_dir)),
    )


def _build_document(
    agent: Agent,
    captured_link_context: CapturedLinkContext,
) -> PagerDocument:
    """Resolve the link context and build the document off the event loop."""
    from ..hints._link_context_capture import link_context_from_capture
    from ._metadata_pager_document import build_agent_metadata_document

    link_context: LinkResolutionContext | None = link_context_from_capture(
        captured_link_context
    )
    return build_agent_metadata_document(agent, link_context=link_context)


def _find_agent_by_identity(
    app: Any,
    identity: tuple[object, ...],
    archive_key: str | None = None,
) -> Agent | None:
    if archive_key is not None:
        from ._archive_actions import archive_read_target, archive_ui_active
        from ._archive_view import get_agents_tab_selection

        if not archive_ui_active(app):
            return None
        selection = get_agents_tab_selection(app)
        agent = archive_read_target(app)
        if selection.archive_key != archive_key:
            return None
        return (
            agent if agent is not None and tuple(agent.identity) == identity else None
        )
    from ._archive_actions import archive_ui_active

    if archive_ui_active(app):
        return None
    for agent in getattr(app, "_agents", ()):
        if tuple(agent.identity) == identity:
            return agent
    return None


def _resolve_ref_from_app_link_index(
    app: Any,
    ref: str,
    *,
    context: LinkResolutionContext | None = None,
) -> Any:
    from ..hints._files import resolve_ref_from_link_index

    return resolve_ref_from_link_index(app, ref, context=context)


class AgentMetadataPagerMixin:
    """Mixin providing the Agents-tab `V` metadata-pager action."""

    def action_view_agent_metadata(self) -> None:
        """Open the selected agent's metadata as a sectioned pager document."""
        with tui_trace("agents.view_agent_metadata"):
            self._action_view_agent_metadata_impl()

    def _action_view_agent_metadata_impl(self) -> None:
        if self.current_tab != "agents":  # type: ignore[attr-defined]
            return
        from ._archive_actions import archive_ui_active, resolve_agents_read_agent

        in_archive = archive_ui_active(self)
        agent = resolve_agents_read_agent(self)
        if agent is None or getattr(agent, "fleet_origin_alias", None):
            return

        archive_key: str | None = None
        if in_archive:
            from ._archive_view import get_agents_tab_selection

            archive_key = get_agents_tab_selection(self).archive_key
            if archive_key is None:
                return

        agent_identity = tuple(agent.identity)
        captured_link_context = _capture_agent_link_context(agent)

        self.run_worker(  # type: ignore[attr-defined]
            self._open_agent_metadata_pager(
                agent, agent_identity, captured_link_context, archive_key
            ),
            group="agent-metadata-pager",
            exclusive=True,
        )

    async def _open_agent_metadata_pager(
        self,
        agent: Agent,
        agent_identity: tuple[object, ...],
        captured_link_context: CapturedLinkContext,
        archive_key: str | None = None,
    ) -> None:
        from sase.pager.screen import PagerScreen
        from sase.pager.syntax_policy import pager_syntax_session_from_config

        document = await asyncio.to_thread(
            _build_document, agent, captured_link_context
        )
        if not self._agent_metadata_pager_selection_is_current(
            agent_identity, archive_key=archive_key
        ):
            return

        def refresh_document_fn() -> PagerDocument | None:
            current = self.call_from_thread(  # type: ignore[attr-defined]
                _find_agent_by_identity, self, agent_identity, archive_key
            )
            if current is None:
                return None
            return _build_document(current, captured_link_context)

        session = pager_syntax_session_from_config()
        screen = PagerScreen(
            document,
            links_enabled=True,
            resolve_ref_fn=lambda ref, *, context=None: (
                _resolve_ref_from_app_link_index(self, ref, context=context)
            ),
            syntax_enabled=session.syntax_enabled,
            refresh_document_fn=refresh_document_fn,
        )
        self.push_screen(screen)  # type: ignore[attr-defined]

    def _agent_metadata_pager_selection_is_current(
        self,
        agent_identity: tuple[object, ...],
        *,
        archive_key: str | None = None,
    ) -> bool:
        if self.current_tab != "agents":  # type: ignore[attr-defined]
            return False
        if archive_key is not None:
            selected = _find_agent_by_identity(
                self, agent_identity, archive_key=archive_key
            )
            return selected is not None and tuple(selected.identity) == agent_identity
        from ._archive_actions import archive_ui_active

        if archive_ui_active(self):
            return False
        selector = getattr(self, "_get_selected_agent", None)
        current = selector() if callable(selector) else None
        return current is not None and tuple(current.identity) == agent_identity


__all__ = ["AgentMetadataPagerMixin"]
