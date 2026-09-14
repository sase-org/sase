"""The `V` metadata-pager action for the Agents tab."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from sase.pager import PagerDocument, PagerScreen
from sase.pager.link_context import LinkResolutionContext
from sase.pager.syntax_policy import pager_syntax_session_from_config

from ...util.trace import tui_trace
from ..hints._files import _resolve_ref_from_link_index
from ..hints._link_context_capture import CapturedLinkContext, link_context_from_capture
from ._metadata_pager_document import build_agent_metadata_document

if TYPE_CHECKING:
    from ...models.agent import Agent


def _capture_agent_link_context(agent: Agent) -> CapturedLinkContext:
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
    link_context: LinkResolutionContext | None = link_context_from_capture(
        captured_link_context
    )
    return build_agent_metadata_document(agent, link_context=link_context)


def _find_agent_by_identity(app: Any, identity: tuple[object, ...]) -> Agent | None:
    for agent in getattr(app, "_agents", ()):
        if tuple(agent.identity) == identity:
            return agent
    return None


class AgentMetadataPagerMixin:
    """Mixin providing the Agents-tab `V` metadata-pager action."""

    def action_view_agent_metadata(self) -> None:
        """Open the selected agent's metadata as a sectioned pager document."""
        with tui_trace("agents.view_agent_metadata"):
            self._action_view_agent_metadata_impl()

    def _action_view_agent_metadata_impl(self) -> None:
        if self.current_tab != "agents":  # type: ignore[attr-defined]
            return
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None or getattr(agent, "fleet_origin_alias", None):
            return

        agent_identity = tuple(agent.identity)
        captured_link_context = _capture_agent_link_context(agent)

        self.run_worker(  # type: ignore[attr-defined]
            self._open_agent_metadata_pager(
                agent, agent_identity, captured_link_context
            ),
            group="agent-metadata-pager",
            exclusive=True,
        )

    async def _open_agent_metadata_pager(
        self,
        agent: Agent,
        agent_identity: tuple[object, ...],
        captured_link_context: CapturedLinkContext,
    ) -> None:
        document = await asyncio.to_thread(
            _build_document, agent, captured_link_context
        )
        if not self._agent_metadata_pager_selection_is_current(agent_identity):
            return

        def refresh_document_fn() -> PagerDocument | None:
            current = self.call_from_thread(  # type: ignore[attr-defined]
                _find_agent_by_identity, self, agent_identity
            )
            if current is None:
                return None
            return _build_document(current, captured_link_context)

        session = pager_syntax_session_from_config()
        screen = PagerScreen(
            document,
            links_enabled=True,
            resolve_ref_fn=lambda ref, *, context=None: _resolve_ref_from_link_index(
                self, ref, context=context
            ),
            syntax_enabled=session.syntax_enabled,
            refresh_document_fn=refresh_document_fn,
        )
        self.push_screen(screen)  # type: ignore[attr-defined]

    def _agent_metadata_pager_selection_is_current(
        self,
        agent_identity: tuple[object, ...],
    ) -> bool:
        if self.current_tab != "agents":  # type: ignore[attr-defined]
            return False
        selected = self._get_selected_agent()  # type: ignore[attr-defined]
        return selected is not None and tuple(selected.identity) == agent_identity


__all__ = ["AgentMetadataPagerMixin"]
